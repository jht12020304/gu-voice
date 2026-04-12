import requests

login_res = requests.post(
    "http://localhost:8000/api/v1/auth/login",
    json={"email":"admin@gu-voice.com","password":"Admin@12345"},
    headers={"Content-Type": "application/json"}
)
print("Login:", login_res.status_code, login_res.text)
token = login_res.json().get("access_token")
if token:
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get("http://localhost:8000/api/v1/complaints", headers=headers)
    print("Complaints GET:", res.status_code)
    print(res.text)
