import asyncio, sys, uuid, json
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/gu_voice"
TAG = "audit-b33"
Q = {
 "queue (status IN + ORDER BY created_at LIMIT 50)": "SELECT id FROM sessions WHERE is_deleted = false AND status IN ('waiting','in_progress') ORDER BY created_at ASC LIMIT 50",
 "sessions today (range predicate, B34)": "SELECT count(*) FROM sessions WHERE is_deleted = false AND created_at >= :d0 AND created_at < :d1",
 "sessions today (old func.date predicate)": "SELECT count(*) FROM sessions WHERE is_deleted = false AND date(created_at) = :today",
 "pending alerts (acknowledged_by IS NULL)": "SELECT count(*) FROM red_flag_alerts WHERE acknowledged_by IS NULL AND session_id IN (SELECT id FROM sessions WHERE is_deleted = false)",
}
async def explain(conn, label, sql, params):
    rows = await conn.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql), params)
    plan = rows.scalar()[0]
    p = plan["Plan"]; 
    def find_scan(node):
        out=[node["Node Type"] + ("(" + node.get("Index Name","") + ")" if "Index Name" in node else "")]
        for c in node.get("Plans", []): out += find_scan(c)
        return out
    print(f"  {label}: {plan['Execution Time']:.2f} ms | nodes: {' > '.join(find_scan(p))}")
    return plan["Execution Time"]
async def main(mode):
    eng = create_async_engine(URL)
    async with eng.begin() as conn:
        if mode == "seed":
            pid = (await conn.execute(text("SELECT id FROM patients LIMIT 1"))).scalar()
            did = (await conn.execute(text("SELECT id FROM users WHERE role IN ('doctor','admin') LIMIT 1"))).scalar()
            cc = (await conn.execute(text("SELECT id FROM chief_complaints LIMIT 1"))).scalar()
            base = datetime(2026, 9, 1, tzinfo=timezone.utc)
            sess = [{"id": str(uuid.uuid4()), "p": str(pid), "d": str(did), "cc": str(cc), "st": ("waiting" if i % 100 == 0 else "in_progress" if i % 100 == 1 else "cancelled" if i % 20 == 2 else "completed"), "ca": base + timedelta(minutes=i*7), "note": TAG} for i in range(100000)]
            await conn.execute(text("INSERT INTO sessions (id, patient_id, doctor_id, chief_complaint_id, status, created_at, updated_at, chief_complaint_text, is_deleted) VALUES (:id, :p, :d, :cc, :st, :ca, :ca, :note, false)"), sess)
            alerts = [{"id": str(uuid.uuid4()), "s": sess[i]["id"], "c": str(uuid.uuid4()), "ca": sess[i]["ca"], "ack": None if i % 3 else str(did), "t": TAG} for i in range(0, 100000, 10)]
            await conn.execute(text("INSERT INTO red_flag_alerts (id, session_id, conversation_id, alert_type, severity, title, trigger_reason, acknowledged_by, language, confidence, created_at) VALUES (:id, :s, :c, 'rule_based', 'high', :t, 'seed', :ack, 'zh-TW', 'rule_hit', :ca)"), alerts)
            print("seeded 100000 sessions (2% active) / 10000 alerts (33% pending)")
        elif mode == "cleanup":
            await conn.execute(text("DELETE FROM red_flag_alerts WHERE title = :t"), {"t": TAG})
            await conn.execute(text("DELETE FROM sessions WHERE chief_complaint_text = :t"), {"t": TAG})
            print("cleanup done")
        else:
            await conn.execute(text("ANALYZE sessions")); await conn.execute(text("ANALYZE red_flag_alerts"))
            today = datetime(2026, 9, 10, tzinfo=timezone.utc)
            for label, sql in Q.items():
                await explain(conn, label, sql, {"d0": today, "d1": today + timedelta(days=1), "today": today.date()})
    await eng.dispose()
asyncio.run(main(sys.argv[1]))
