#!/usr/bin/env bash
# =============================================================================
# verify_multilang_migration.sh
#
# 對 Alembic migration c3d4e5f6a7b8 (add_multilang_fields) 做 live round-trip：
#     upgrade head → downgrade -1 → upgrade head
# 並在每一階段檢查四個多語欄位是否符合預期。
#
# 安全設計：
#   - 跑在一個 **暫時** 的 Docker Postgres container（name: gu_migration_test_pg，
#     port 55432），不碰任何共用 / production DB。
#   - 不讀取 / 覆寫 backend/.env（會以 env var 覆寫 DB_* 指向 temp container）。
#   - 每次執行都會強制 recreate container，保證 migration 從乾淨的 DB 開始跑。
#
# 使用：
#   bash scripts/verify_multilang_migration.sh
#
# 依賴：docker, backend/venv (含 alembic + psycopg2), psql (或 docker exec)
# =============================================================================

set -euo pipefail

CONTAINER="gu_migration_test_pg"
PGPORT="55432"
PGUSER="postgres"
PGPASS="postgres"
PGDB="gu_voice"
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../backend" && pwd)"

log() { printf '\n\033[1;34m[verify]\033[0m %s\n' "$*"; }
err() { printf '\n\033[1;31m[verify-ERROR]\033[0m %s\n' "$*" >&2; }

psql_q() {
    # execute SQL against the temp container and print tuples only
    docker exec -e PGPASSWORD="$PGPASS" "$CONTAINER" \
        psql -U "$PGUSER" -d "$PGDB" -tA -c "$1"
}

assert_column_exists() {
    local table="$1" col="$2"
    local got
    got=$(psql_q "SELECT column_name FROM information_schema.columns
                  WHERE table_name='$table' AND column_name='$col';")
    if [[ "$got" != "$col" ]]; then
        err "expected column $table.$col to exist, got: '$got'"
        return 1
    fi
    echo "  ok: $table.$col exists"
}

assert_column_absent() {
    local table="$1" col="$2"
    local got
    got=$(psql_q "SELECT column_name FROM information_schema.columns
                  WHERE table_name='$table' AND column_name='$col';")
    if [[ -n "$got" ]]; then
        err "expected column $table.$col to NOT exist, but found"
        return 1
    fi
    echo "  ok: $table.$col absent"
}

assert_column_notnull() {
    local table="$1" col="$2" want="$3"  # want = YES / NO
    local got
    got=$(psql_q "SELECT is_nullable FROM information_schema.columns
                  WHERE table_name='$table' AND column_name='$col';")
    if [[ "$got" != "$want" ]]; then
        err "$table.$col is_nullable='$got' (want '$want')"
        return 1
    fi
    echo "  ok: $table.$col is_nullable=$got"
}

assert_default_contains() {
    local table="$1" col="$2" needle="$3"
    local got
    got=$(psql_q "SELECT column_default FROM information_schema.columns
                  WHERE table_name='$table' AND column_name='$col';")
    if [[ "$got" != *"$needle"* ]]; then
        err "$table.$col default='$got' (want contains '$needle')"
        return 1
    fi
    echo "  ok: $table.$col default contains '$needle'"
}

assert_index_exists() {
    local idx="$1"
    local got
    got=$(psql_q "SELECT indexname FROM pg_indexes WHERE indexname='$idx';")
    if [[ "$got" != "$idx" ]]; then
        err "expected index $idx to exist, got: '$got'"
        return 1
    fi
    echo "  ok: index $idx exists"
}

assert_index_absent() {
    local idx="$1"
    local got
    got=$(psql_q "SELECT indexname FROM pg_indexes WHERE indexname='$idx';")
    if [[ -n "$got" ]]; then
        err "expected index $idx to NOT exist, but found"
        return 1
    fi
    echo "  ok: index $idx absent"
}

# ── 1. 重置 container ───────────────────────────────────────────────
log "recreating temp Postgres container ($CONTAINER on :$PGPORT)…"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --rm --name "$CONTAINER" \
    -e POSTGRES_DB="$PGDB" \
    -e POSTGRES_USER="$PGUSER" \
    -e POSTGRES_PASSWORD="$PGPASS" \
    -p "$PGPORT:5432" \
    postgres:16-alpine >/dev/null

# wait for ready
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if docker exec "$CONTAINER" pg_isready -U "$PGUSER" >/dev/null 2>&1; then
        log "postgres ready after ${i}s"
        break
    fi
    sleep 1
done

# ── 2. 設定 alembic 連線（透過 env var 覆寫 Settings） ──────────────
export DB_HOST="127.0.0.1"
export DB_PORT="$PGPORT"
export DB_NAME="$PGDB"
export DB_USER="$PGUSER"
export DB_PASSWORD="$PGPASS"
# 顯式 URL 取消，以免 backend/.env 的 Supabase URL 被讀到
unset DATABASE_URL || true

cd "$BACKEND_DIR"
ALEMBIC="$BACKEND_DIR/venv/bin/alembic"

# ── 3. 第一次 upgrade head ─────────────────────────────────────────
log "alembic upgrade head (first time)…"
"$ALEMBIC" upgrade head

log "checking four multilang columns exist after initial upgrade…"
assert_column_exists "users" "preferred_language"
assert_column_notnull "users" "preferred_language" "YES"

assert_column_exists "soap_reports" "language"
assert_column_notnull "soap_reports" "language" "NO"
assert_default_contains "soap_reports" "language" "zh-TW"

assert_column_exists "red_flag_alerts" "language"
assert_column_notnull "red_flag_alerts" "language" "NO"
assert_default_contains "red_flag_alerts" "language" "zh-TW"

assert_column_exists "audit_logs" "language"
assert_column_notnull "audit_logs" "language" "YES"
assert_index_exists "ix_audit_logs_language"

# ── 4. downgrade -1 ────────────────────────────────────────────────
log "alembic downgrade -1 (undo add_multilang_fields)…"
"$ALEMBIC" downgrade -1

log "checking four multilang columns are gone after downgrade…"
assert_column_absent "users" "preferred_language"
assert_column_absent "soap_reports" "language"
assert_column_absent "red_flag_alerts" "language"
assert_column_absent "audit_logs" "language"
assert_index_absent "ix_audit_logs_language"

# ── 5. 再次 upgrade head ───────────────────────────────────────────
log "alembic upgrade head (second time, re-apply add_multilang_fields)…"
"$ALEMBIC" upgrade head

log "re-checking four multilang columns after second upgrade…"
assert_column_exists "users" "preferred_language"
assert_column_exists "soap_reports" "language"
assert_column_exists "red_flag_alerts" "language"
assert_column_exists "audit_logs" "language"
assert_index_exists "ix_audit_logs_language"
assert_default_contains "soap_reports" "language" "zh-TW"
assert_default_contains "red_flag_alerts" "language" "zh-TW"

# ── 6. 驗證 partitioned audit_logs 的子分區也有 language 欄位 ─────
log "verifying audit_logs child partitions inherited language column…"
PART_WITHOUT_LANG=$(psql_q "
    WITH partitions AS (
        SELECT inhrelid::regclass::text AS child
        FROM pg_inherits
        WHERE inhparent = 'audit_logs'::regclass
    )
    SELECT child FROM partitions
    WHERE child NOT IN (
        SELECT table_name FROM information_schema.columns
        WHERE column_name='language' AND table_name LIKE 'audit_logs%'
    );")
if [[ -n "$PART_WITHOUT_LANG" ]]; then
    err "some audit_logs partitions missing language column: $PART_WITHOUT_LANG"
    exit 1
fi
echo "  ok: all audit_logs partitions have language column"

# ── 7. 清理 ───────────────────────────────────────────────────────
log "all checks passed; stopping temp container"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

log "DONE — migration c3d4e5f6a7b8 passes upgrade→downgrade→upgrade round-trip"
