"""Seed doctor/admin/report data in the isolated UI-test Compose database only."""
import json
import subprocess
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:18083/api/v1"
COMPOSE = ["docker", "compose", "-f", "ios_native/TestsSupport/kiosk-compose.yml"]
PASSWORD = "Kiosk-fixture9!"


def register(email: str, name: str) -> None:
    body = json.dumps({"email": email, "password": PASSWORD, "name": name, "role": "patient"}).encode()
    request = urllib.request.Request(f"{BASE}/auth/register", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 201
    except urllib.error.HTTPError as error:
        if error.code not in (409, 429):
            raise


for email, name in [
    ("kiosk-doctor@example.com", "QA Doctor"),
    ("kiosk-admin@example.com", "QA System Admin"),
    ("kiosk-patient@example.com", "QA Patient"),
]:
    register(email, name)

doctor_id = str(uuid.uuid4())
patient_id = str(uuid.uuid4())
session_id = str(uuid.uuid4())
report_id = str(uuid.uuid4())
conversation_id = str(uuid.uuid4())
alert_id = str(uuid.uuid4())

sql = f"""
INSERT INTO users (email, password_hash, name, role, is_active)
SELECT 'kiosk-admin@example.com', password_hash, 'QA System Admin', 'admin', true
FROM users WHERE email = 'kiosk-patient@example.com'
ON CONFLICT (email) DO NOTHING;
UPDATE users SET id = id, role = 'doctor', license_number = 'QA-001', department = 'Urology'
 WHERE email = 'kiosk-doctor@example.com';
UPDATE users SET role = 'admin', license_number = NULL, department = 'Administration'
 WHERE email = 'kiosk-admin@example.com';
UPDATE users SET role = 'patient' WHERE email = 'kiosk-patient@example.com';
INSERT INTO patients (id, user_id, medical_record_number, name, gender, date_of_birth)
SELECT '{patient_id}', id, 'QA-CLINICAL-001', 'Synthetic Patient', 'male', DATE '1980-01-01'
FROM users WHERE email = 'kiosk-patient@example.com'
ON CONFLICT (medical_record_number) DO NOTHING;
INSERT INTO chief_complaints (id, name, name_en, category, name_by_lang, category_by_lang, is_default, is_active)
VALUES ('{uuid.uuid4()}', '頻尿', 'Frequent urination', 'urinary', '{{"zh-TW":"頻尿","en-US":"Frequent urination"}}', '{{"zh-TW":"泌尿症狀","en-US":"Urinary symptoms"}}', true, true)
ON CONFLICT DO NOTHING;
INSERT INTO sessions (id, patient_id, doctor_id, chief_complaint_id, chief_complaint_text, status, red_flag, red_flag_reason, language, intake_completed_at, started_at, completed_at)
SELECT '{session_id}', p.id, u.id, c.id, 'Frequent urination', 'completed', true, 'Synthetic red flag for UI review', 'en-US', now(), now(), now()
FROM patients p, users u, chief_complaints c
WHERE p.medical_record_number = 'QA-CLINICAL-001' AND u.email = 'kiosk-doctor@example.com' AND c.name_en = 'Frequent urination'
ON CONFLICT (id) DO NOTHING;
INSERT INTO conversations (id, session_id, sequence_number, role, content_text, red_flag_detected)
VALUES ('{conversation_id}', '{session_id}', 1, 'patient', 'I have had frequent urination for three days.', true)
ON CONFLICT DO NOTHING;
INSERT INTO soap_reports (id, session_id, status, review_status, subjective, objective, assessment, plan, raw_transcript, summary, language, generated_at)
VALUES ('{report_id}', '{session_id}', 'generated', 'pending',
 '{{"chief_complaint":"Frequent urination","hpi":"Three days"}}',
 '{{"vital_signs":"Stable"}}',
 '{{"clinical_impression":"Synthetic review case"}}',
 '{{"recommended_tests":[{{"test_name":"Urinalysis","rationale":"UI fixture"}}]}}',
 'Patient: I have had frequent urination for three days.\\nAssistant: Thank you.',
 'Synthetic generated report for native UI tests.', 'en-US', now())
ON CONFLICT (session_id) DO UPDATE SET status = 'generated', review_status = 'pending';
INSERT INTO red_flag_alerts (id, session_id, conversation_id, alert_type, severity, title, trigger_reason, language, confidence)
VALUES ('{alert_id}', '{session_id}', '{conversation_id}', 'rule_based', 'high', 'Synthetic red flag', 'Synthetic fixture alert', 'en-US', 'rule_hit')
ON CONFLICT DO NOTHING;
"""
subprocess.run(COMPOSE + ["exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "kiosk"], input=sql, text=True, check=True)
