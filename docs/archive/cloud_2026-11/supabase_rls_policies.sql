-- =============================================================================
-- GU-Voice Supabase Row-Level Security (RLS) 政策
-- =============================================================================
--
-- P2 #16：為 sessions / soap_reports / red_flag_alerts / notifications 四表
-- 建立 RLS，確保在 Supabase 直連（例：前端用 anon key / 病患 JWT 查詢）時：
--   - 病患只能看到自己的資料
--   - 醫師只能看到指派給自己或未指派的場次
--   - admin 全開
--
-- 背景
-- ----
-- 後端 FastAPI 使用 service_role key 連 DB → RLS 自動 bypass，不影響後端邏輯。
-- RLS 是 defense-in-depth，針對：
--   1. 前端直連 Supabase（若未來引入）
--   2. 誤用匿名 key 的請求
--   3. 防止 service role 外洩時的災難性全表讀取（bypass 需要 service_role 這把鑰匙）
--
-- 角色對應（users.role enum：patient / doctor / admin）
--   - patient：可讀自己 patients.user_id = auth.uid() 對應的場次鏈
--   - doctor： doctor_id = auth.uid() 或 doctor_id IS NULL（候補排隊）的場次
--   - admin：  全開
--
-- 使用方式
-- --------
--   \i docs/supabase_rls_policies.sql           -- psql 本機測
--   or paste into Supabase SQL Editor           -- 生產直接套用
--
-- 驗收
-- ----
-- 用病患 A 的 JWT（含 sub=<userA>）呼叫：
--   SET LOCAL ROLE authenticated;
--   SET LOCAL request.jwt.claims = '{"sub":"<userA-uuid>","role":"patient"}';
--   SELECT * FROM sessions WHERE id = '<sessionB-belongs-to-patientB>';
--   → 0 rows
--
-- 所有 `DROP POLICY IF EXISTS ... ; CREATE POLICY ...` 寫法保證可重跑。

BEGIN;

-- ──────────────────────────────────────────────────────────
-- 0. 輔助函式：判斷當前使用者角色 / 病患身分
-- ──────────────────────────────────────────────────────────

-- 讀 users.role（不走 JWT 自訂 claim，避免手刻 claim 出錯）
-- STABLE：同一 statement 內結果不變，可被 planner 快取
CREATE OR REPLACE FUNCTION public.gu_current_user_role()
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT role::text FROM public.users WHERE id = auth.uid();
$$;

CREATE OR REPLACE FUNCTION public.gu_is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT public.gu_current_user_role() = 'admin';
$$;

CREATE OR REPLACE FUNCTION public.gu_is_doctor_or_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT public.gu_current_user_role() IN ('doctor', 'admin');
$$;

-- 當前登入使用者對應的 patients.id（病患才有；醫師/管理員得 NULL）
CREATE OR REPLACE FUNCTION public.gu_current_patient_id()
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT id FROM public.patients WHERE user_id = auth.uid() LIMIT 1;
$$;

-- 讓 RLS policy 呼叫得到（service_role 自動 bypass，不需要 grant；anon 不需要）
GRANT EXECUTE ON FUNCTION public.gu_current_user_role() TO authenticated;
GRANT EXECUTE ON FUNCTION public.gu_is_admin() TO authenticated;
GRANT EXECUTE ON FUNCTION public.gu_is_doctor_or_admin() TO authenticated;
GRANT EXECUTE ON FUNCTION public.gu_current_patient_id() TO authenticated;


-- ──────────────────────────────────────────────────────────
-- 1. sessions：問診場次
-- ──────────────────────────────────────────────────────────

ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "sessions: patient reads own"       ON public.sessions;
DROP POLICY IF EXISTS "sessions: doctor reads assigned"   ON public.sessions;
DROP POLICY IF EXISTS "sessions: admin full read"         ON public.sessions;
DROP POLICY IF EXISTS "sessions: patient creates own"     ON public.sessions;
DROP POLICY IF EXISTS "sessions: doctor updates assigned" ON public.sessions;

-- 讀：病患看自己；醫師看指派給自己或待分派；admin 全開
CREATE POLICY "sessions: patient reads own"
ON public.sessions FOR SELECT
TO authenticated
USING (patient_id = public.gu_current_patient_id());

CREATE POLICY "sessions: doctor reads assigned"
ON public.sessions FOR SELECT
TO authenticated
USING (
    public.gu_current_user_role() = 'doctor'
    AND (doctor_id = auth.uid() OR doctor_id IS NULL)
);

CREATE POLICY "sessions: admin full read"
ON public.sessions FOR SELECT
TO authenticated
USING (public.gu_is_admin());

-- 寫：病患可建立自己名下的場次
CREATE POLICY "sessions: patient creates own"
ON public.sessions FOR INSERT
TO authenticated
WITH CHECK (patient_id = public.gu_current_patient_id());

-- 更新：醫師可改自己負責的場次；admin 全開
CREATE POLICY "sessions: doctor updates assigned"
ON public.sessions FOR UPDATE
TO authenticated
USING (
    (public.gu_current_user_role() = 'doctor' AND doctor_id = auth.uid())
    OR public.gu_is_admin()
)
WITH CHECK (
    (public.gu_current_user_role() = 'doctor' AND doctor_id = auth.uid())
    OR public.gu_is_admin()
);


-- ──────────────────────────────────────────────────────────
-- 2. soap_reports：SOAP 報告
-- ──────────────────────────────────────────────────────────

ALTER TABLE public.soap_reports ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "soap: patient reads own via session"   ON public.soap_reports;
DROP POLICY IF EXISTS "soap: doctor reads assigned session"   ON public.soap_reports;
DROP POLICY IF EXISTS "soap: admin full read"                 ON public.soap_reports;
DROP POLICY IF EXISTS "soap: doctor reviews assigned session" ON public.soap_reports;

-- 讀：依 sessions 所有權判斷
CREATE POLICY "soap: patient reads own via session"
ON public.soap_reports FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM public.sessions s
        WHERE s.id = soap_reports.session_id
          AND s.patient_id = public.gu_current_patient_id()
    )
);

CREATE POLICY "soap: doctor reads assigned session"
ON public.soap_reports FOR SELECT
TO authenticated
USING (
    public.gu_current_user_role() = 'doctor'
    AND EXISTS (
        SELECT 1 FROM public.sessions s
        WHERE s.id = soap_reports.session_id
          AND (s.doctor_id = auth.uid() OR s.doctor_id IS NULL)
    )
);

CREATE POLICY "soap: admin full read"
ON public.soap_reports FOR SELECT
TO authenticated
USING (public.gu_is_admin());

-- 更新：醫師審閱自己負責場次的報告
CREATE POLICY "soap: doctor reviews assigned session"
ON public.soap_reports FOR UPDATE
TO authenticated
USING (
    (
        public.gu_current_user_role() = 'doctor'
        AND EXISTS (
            SELECT 1 FROM public.sessions s
            WHERE s.id = soap_reports.session_id AND s.doctor_id = auth.uid()
        )
    )
    OR public.gu_is_admin()
)
WITH CHECK (
    (
        public.gu_current_user_role() = 'doctor'
        AND EXISTS (
            SELECT 1 FROM public.sessions s
            WHERE s.id = soap_reports.session_id AND s.doctor_id = auth.uid()
        )
    )
    OR public.gu_is_admin()
);


-- ──────────────────────────────────────────────────────────
-- 3. red_flag_alerts：紅旗警示
-- ──────────────────────────────────────────────────────────

ALTER TABLE public.red_flag_alerts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "red_flag: patient reads own via session" ON public.red_flag_alerts;
DROP POLICY IF EXISTS "red_flag: doctor reads assigned session" ON public.red_flag_alerts;
DROP POLICY IF EXISTS "red_flag: admin full read"               ON public.red_flag_alerts;
DROP POLICY IF EXISTS "red_flag: doctor acknowledges"           ON public.red_flag_alerts;

CREATE POLICY "red_flag: patient reads own via session"
ON public.red_flag_alerts FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM public.sessions s
        WHERE s.id = red_flag_alerts.session_id
          AND s.patient_id = public.gu_current_patient_id()
    )
);

CREATE POLICY "red_flag: doctor reads assigned session"
ON public.red_flag_alerts FOR SELECT
TO authenticated
USING (
    public.gu_current_user_role() = 'doctor'
    AND EXISTS (
        SELECT 1 FROM public.sessions s
        WHERE s.id = red_flag_alerts.session_id
          AND (s.doctor_id = auth.uid() OR s.doctor_id IS NULL)
    )
);

CREATE POLICY "red_flag: admin full read"
ON public.red_flag_alerts FOR SELECT
TO authenticated
USING (public.gu_is_admin());

-- 只有醫師或管理員能 acknowledge；更新限定自己負責或全開的 admin
CREATE POLICY "red_flag: doctor acknowledges"
ON public.red_flag_alerts FOR UPDATE
TO authenticated
USING (
    (
        public.gu_current_user_role() = 'doctor'
        AND EXISTS (
            SELECT 1 FROM public.sessions s
            WHERE s.id = red_flag_alerts.session_id
              AND (s.doctor_id = auth.uid() OR s.doctor_id IS NULL)
        )
    )
    OR public.gu_is_admin()
)
WITH CHECK (
    (
        public.gu_current_user_role() = 'doctor'
        AND EXISTS (
            SELECT 1 FROM public.sessions s
            WHERE s.id = red_flag_alerts.session_id
              AND (s.doctor_id = auth.uid() OR s.doctor_id IS NULL)
        )
    )
    OR public.gu_is_admin()
);


-- ──────────────────────────────────────────────────────────
-- 4. notifications：站內通知
-- ──────────────────────────────────────────────────────────

ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "notif: user reads own"       ON public.notifications;
DROP POLICY IF EXISTS "notif: admin full read"      ON public.notifications;
DROP POLICY IF EXISTS "notif: user updates own"     ON public.notifications;

-- 讀：收件人自己（user_id 直接對 auth.uid()）
CREATE POLICY "notif: user reads own"
ON public.notifications FOR SELECT
TO authenticated
USING (user_id = auth.uid());

CREATE POLICY "notif: admin full read"
ON public.notifications FOR SELECT
TO authenticated
USING (public.gu_is_admin());

-- 更新：收件人自己可改 read_at 等狀態欄
CREATE POLICY "notif: user updates own"
ON public.notifications FOR UPDATE
TO authenticated
USING (user_id = auth.uid())
WITH CHECK (user_id = auth.uid());


-- ──────────────────────────────────────────────────────────
-- 5.（選用）conversations：逐句對話紀錄（partitioned table）
-- ──────────────────────────────────────────────────────────
-- 若前端未直接查詢 conversations 可以先不啟用；啟用後：
--     ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
-- 並新增一條 SELECT policy 沿 session ownership 推斷即可。
-- 目前保守：僅後端 service_role 讀取，RLS 暫不開。


COMMIT;

-- ──────────────────────────────────────────────────────────
-- 驗收測試腳本（手動貼到 SQL Editor 跑）
-- ──────────────────────────────────────────────────────────
-- -- 1) 假裝自己是病患 A
-- SET LOCAL ROLE authenticated;
-- SET LOCAL "request.jwt.claims" = '{"sub":"<userA-uuid>","role":"authenticated"}';
-- SELECT id FROM public.sessions;                -- 應只看到 A 名下
-- SELECT id FROM public.soap_reports;            -- 應只看到 A 場次對應的
-- SELECT id FROM public.red_flag_alerts;         -- 同上
-- SELECT id FROM public.notifications;           -- 應只看到 user_id=A
--
-- -- 2) 假裝自己是醫師 D（未被指派 sessionA）
-- SET LOCAL "request.jwt.claims" = '{"sub":"<doctorD-uuid>","role":"authenticated"}';
-- SELECT id FROM public.sessions WHERE id = '<sessionA-id>';
-- -- → 0 rows（doctor_id IS NULL 例外通過；指派給他人則被擋）
--
-- -- 3) admin 應全開
-- SET LOCAL "request.jwt.claims" = '{"sub":"<adminUid>","role":"authenticated"}';
-- SELECT COUNT(*) FROM public.sessions;          -- 全表
