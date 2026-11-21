"""Create synthetic accounts only in the isolated simulator fixture."""
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

compose = Path(__file__).with_name("kiosk-compose.yml")
for kind in ("doctor", "patient"):
    payload = {"email": f"kiosk-{kind}@example.com", "password": "Kiosk-fixture9!",
               "name": f"QA {kind.title()}", "role": "patient"}
    request = urllib.request.Request("http://127.0.0.1:18083/api/v1/auth/register",
                                     data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 201
    except urllib.error.HTTPError as error:
        if error.code != 409:
            raise
subprocess.run(["docker", "compose", "-f", str(compose), "exec", "-T", "postgres",
                "psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "kiosk", "-c",
                "UPDATE users SET role='doctor', license_number='QA-001', department='Urology' "
                "WHERE email='kiosk-doctor@example.com'"], check=True)
