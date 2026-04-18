"""backfill legacy chief_complaints multilang + deactivate duplicates — TODO B1-follow-up

情境：20260418_1900 的 seed migration 以固定 UUID（c1~c9 + 0a）插入 10 筆多語主訴，
但 DB 內仍殘留先前手動/舊 migration 插入的「只有 zh-TW（+en-US）legacy 欄位、
`*_by_lang` 未完整」的記錄，於 ja/ko/vi 場次會：
  1) fallback 成 zh-TW 文字（例如韓文頁面出現「血尿」「頻尿」中文卡片）
  2) 其 `category` 仍是舊 zh-TW 字串，與 seed 的 `배뇨 증상` 分開成兩組（畫面
     出現同一類別重複 section）。

本 migration 目標（已修訂）：
  B. 對「非 seed 但有 canonical 英文名的常見泌尿科主訴」（例如 Nocturia、
     Burning sensation during urination、Dysuria/Difficulty urinating），以
     `name_by_lang || '{...}'::jsonb` 非破壞性 merge 的方式補齊 ja/ko/vi 翻譯，
     description_by_lang / category_by_lang 同法處理。

  A 段（軟停用重覆記錄）已移除：
    原本 `id NOT IN ('uuid-string', ...)` 在線上 PostgreSQL 對 UUID 欄位的
    隱式 cast 行為不穩，實際跑出來把 seed 本身也一起停掉，造成主訴列表空白
    （由 20260418_2330 rescue migration 救回）。後續 dedup 改由另一支
    migration 在確認 DB 實際狀態後以 `id NOT IN (array[...]::uuid[])` 的
    精準語法執行；在此之前寧可讓舊中文卡片暫時又出現，也不要整個列表空白。

設計原則：
  - **不刪資料**：全程 UPDATE，是 JSONB 補譯，可被 downgrade 移除。
  - **只處理 active 記錄**：不動先前已被管理端停用的主訴。

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-04-18 23:00:00.000000+08:00
"""

import json
from typing import Sequence, Union

from alembic import op


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 20260418_1900 seed 寫入的固定 UUID —— 這些是「正本」，不得被本 migration 動到
SEED_UUIDS: list[str] = [
    "00000000-0000-4000-8000-0000000000c1",
    "00000000-0000-4000-8000-0000000000c2",
    "00000000-0000-4000-8000-0000000000c3",
    "00000000-0000-4000-8000-0000000000c4",
    "00000000-0000-4000-8000-0000000000c5",
    "00000000-0000-4000-8000-0000000000c6",
    "00000000-0000-4000-8000-0000000000c7",
    "00000000-0000-4000-8000-0000000000c8",
    "00000000-0000-4000-8000-0000000000c9",
    "00000000-0000-4000-8000-00000000000a",
]


# A. 依 zh-TW legacy `name` 辨識「seed 重覆記錄」→ 軟停用
#    這些 name 在 seed 已有權威多語版本，舊記錄直接停用避免雙份渲染。
DUPLICATE_ZHTW_NAMES: list[str] = [
    "血尿",      # seed c1 — Hematuria
    "頻尿",      # seed c2 — Frequent urination
    "排尿疼痛",  # seed c3 — Dysuria
    "尿失禁",    # seed c4 — Urinary incontinence
    "腰痛",      # seed c5 — Flank pain
    "下腹痛",    # seed c6 — Lower abdominal pain
    "陰囊腫脹",  # seed c7 — Scrotal swelling
    "勃起功能障礙",  # seed c8 — Erectile dysfunction
    "PSA 異常",  # seed c9 — Elevated PSA
    "尿液檢查異常",  # seed 0a — Abnormal urinalysis
]


# 共用分類翻譯（與 20260418_1900 seed 對齊）
CATEGORY_I18N = {
    "urinary": {
        "zh-TW": "排尿症狀",
        "en-US": "Urinary symptoms",
        "ja-JP": "排尿症状",
        "ko-KR": "배뇨 증상",
        "vi-VN": "Triệu chứng tiết niệu",
    },
    "pain": {
        "zh-TW": "疼痛",
        "en-US": "Pain",
        "ja-JP": "疼痛",
        "ko-KR": "통증",
        "vi-VN": "Đau",
    },
    "abnormal": {
        "zh-TW": "檢查異常",
        "en-US": "Abnormal findings",
        "ja-JP": "検査異常",
        "ko-KR": "검사 이상",
        "vi-VN": "Kết quả xét nghiệm bất thường",
    },
    "other": {
        "zh-TW": "其他",
        "en-US": "Other",
        "ja-JP": "その他",
        "ko-KR": "기타",
        "vi-VN": "Khác",
    },
}


# B. 不在 seed 但常見的泌尿主訴 → 補齊多語翻譯
#    key 以 zh-TW legacy name 命中 UPDATE；description 以舊畫面 description 對齊。
LEGACY_BACKFILL: list[dict] = [
    {
        "match_name_zh": "排尿困難",
        "category_key": "urinary",
        "name": {
            "zh-TW": "排尿困難",
            "en-US": "Dysuria / Difficulty urinating",
            "ja-JP": "排尿困難",
            "ko-KR": "배뇨 곤란",
            "vi-VN": "Khó tiểu",
        },
        "description": {
            "zh-TW": "排尿時感到困難，包括尿流變細、排尿費力、尿不乾淨等",
            "en-US": "Difficulty urinating, including weak stream, straining, incomplete emptying",
            "ja-JP": "排尿が困難で、尿の勢いが弱い・いきみが必要・残尿感などがある",
            "ko-KR": "배뇨가 어렵고 소변 줄기가 가늘거나 힘을 주어야 하며 잔뇨감이 있음",
            "vi-VN": "Khó đi tiểu, tia nước tiểu yếu, phải rặn, cảm giác tiểu không hết",
        },
    },
    {
        "match_name_zh": "夜尿",
        "category_key": "urinary",
        "name": {
            "zh-TW": "夜尿",
            "en-US": "Nocturia",
            "ja-JP": "夜間頻尿",
            "ko-KR": "야간뇨",
            "vi-VN": "Tiểu đêm",
        },
        "description": {
            "zh-TW": "夜間因排尿需求而中斷睡眠，通常每晚 2 次以上",
            "en-US": "Waking at night to urinate, typically two or more times per night",
            "ja-JP": "排尿のため夜間に目が覚める。通常は一晩に 2 回以上",
            "ko-KR": "야간에 소변 때문에 잠이 깨며, 보통 하룻밤에 2회 이상",
            "vi-VN": "Thức giấc ban đêm để đi tiểu, thường từ 2 lần trở lên mỗi đêm",
        },
    },
    {
        "match_name_zh": "尿道灼熱感",
        "category_key": "urinary",
        "name": {
            "zh-TW": "尿道灼熱感",
            "en-US": "Burning sensation during urination",
            "ja-JP": "排尿時の灼熱感",
            "ko-KR": "배뇨 시 작열감",
            "vi-VN": "Cảm giác rát khi đi tiểu",
        },
        "description": {
            "zh-TW": "排尿時尿道有灼熱或刺痛感，可能為泌尿道感染的徵兆",
            "en-US": "Burning or stinging sensation in the urethra when urinating; possible sign of a urinary tract infection",
            "ja-JP": "排尿時に尿道が灼けるような・刺すような痛みがあり、尿路感染症の兆候の可能性",
            "ko-KR": "배뇨 시 요도에 작열감이나 찌르는 통증이 있으며, 요로 감염의 징후일 수 있음",
            "vi-VN": "Cảm giác nóng rát hoặc châm chích ở niệu đạo khi đi tiểu, có thể là dấu hiệu nhiễm trùng đường tiết niệu",
        },
    },
]


def _sql_literal(text_value: str) -> str:
    """PostgreSQL 單引號 literal；內層單引號以雙引號逃逸。"""
    return "'" + text_value.replace("'", "''") + "'"


def _jsonb_literal(payload: dict) -> str:
    """dict → '{...}'::jsonb，`ensure_ascii=False` 保留 Unicode 原字。"""
    return _sql_literal(json.dumps(payload, ensure_ascii=False)) + "::jsonb"


def _seed_ids_sql() -> str:
    return ", ".join(_sql_literal(sid) for sid in SEED_UUIDS)


def upgrade() -> None:
    # A. 軟停用（已移除）—— 原邏輯參見 module docstring
    #    後續 dedup 等確認 DB 狀態後以另一支 migration 精準處理。

    # B. 非 seed 常見主訴 → 以 JSONB concat 補齊多語欄位
    #    用 COALESCE + || 保留原有 key（zh-TW 已存在就不覆蓋，ja/ko/vi 若 target
    #    原本沒 key 會被補上）。以 name match 精準鎖定 3 筆 legacy 記錄；
    #    不使用 `id NOT IN (seeds)` —— 這些 name 與 seed 的 zh-TW name 不相同，
    #    不會誤觸 seed。
    for entry in LEGACY_BACKFILL:
        match_name = _sql_literal(entry["match_name_zh"])
        category = CATEGORY_I18N[entry["category_key"]]
        op.execute(
            f"""
            UPDATE chief_complaints
            SET name_by_lang = COALESCE(name_by_lang, '{{}}'::jsonb) || {_jsonb_literal(entry["name"])},
                description_by_lang = COALESCE(description_by_lang, '{{}}'::jsonb) || {_jsonb_literal(entry["description"])},
                category_by_lang = COALESCE(category_by_lang, '{{}}'::jsonb) || {_jsonb_literal(category)},
                updated_at = NOW()
            WHERE name = {match_name}
              AND is_active = true
            """
        )


def downgrade() -> None:
    # 還原 B：從 *_by_lang 移除本次補上的 ja/ko/vi key
    #  (zh-TW / en-US 保留 —— 舊記錄原本就有)
    removed_locales = ["ja-JP", "ko-KR", "vi-VN"]
    remove_keys_sql = " - ".join(f"'{loc}'" for loc in removed_locales)
    for entry in LEGACY_BACKFILL:
        match_name = _sql_literal(entry["match_name_zh"])
        op.execute(
            f"""
            UPDATE chief_complaints
            SET name_by_lang = name_by_lang - {remove_keys_sql},
                description_by_lang = description_by_lang - {remove_keys_sql},
                category_by_lang = category_by_lang - {remove_keys_sql},
                updated_at = NOW()
            WHERE name = {match_name}
            """
        )
