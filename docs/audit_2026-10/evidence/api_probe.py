import asyncio, json, os, statistics, subprocess, sys, time, threading
import httpx

BASE = os.environ.get("PROBE_BASE", "http://127.0.0.1:18000")
S = os.path.dirname(os.path.abspath(__file__))
EMAIL = open(os.path.join(S, "audit_account.txt")).read().strip()
PASSWORD = "AuditPass2026x"
N = int(os.environ.get("PROBE_N", "30"))
LABEL = os.environ.get("PROBE_LABEL", "baseline")
PID = int(os.environ.get("PROBE_PID", "0"))

def rss_mb(pid):
    try:
        out = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)]).decode().strip()
        return int(out) / 1024
    except Exception:
        return None

class RssSampler(threading.Thread):
    def __init__(self, pid):
        super().__init__(daemon=True); self.pid = pid; self.samples = []; self.stop = False
    def run(self):
        while not self.stop:
            v = rss_mb(self.pid)
            if v: self.samples.append(v)
            time.sleep(0.25)

DEFAULTS = {"month": "2026-10", "year": "2026", "date": "2026-10-22", "day": "2026-10-22",
            "date_from": "2026-10-01T00:00:00+08:00", "date_to": "2026-10-31T23:59:59+08:00",
            "language": "zh-TW", "lng": "zh-TW", "limit": "20", "page_size": "20", "days": "30"}

def pct(xs, p):
    xs = sorted(xs); k = max(0, min(len(xs)-1, int(round((p/100)*len(xs)+0.5))-1)); return xs[k]

async def timed(client, method, url, n, **kw):
    lat, codes = [], {}
    for _ in range(n):
        t0 = time.perf_counter(); r = await client.request(method, url, **kw); dt = (time.perf_counter()-t0)*1000
        lat.append(dt); codes[r.status_code] = codes.get(r.status_code, 0)+1
    return {"n": n, "p50_ms": round(statistics.median(lat),1), "p95_ms": round(pct(lat,95),1), "max_ms": round(max(lat),1), "mean_ms": round(statistics.mean(lat),1), "codes": codes}

async def main():
    spec = json.load(open(os.path.join(S, "openapi.json")))
    sampler = RssSampler(PID) if PID else None
    if sampler: sampler.start()
    results = {"label": LABEL, "base": BASE, "n": N, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "endpoints": {}, "skipped": {}}
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        # login (bcrypt path) measured separately
        for attempt in range(8):
            r = await c.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
            if r.status_code == 200: break
            print("login status", r.status_code, "waiting 15s for rate-limit window"); await asyncio.sleep(15)
        tok = r.json()["access_token"]
        results["endpoints"]["POST /auth/login"] = await timed(c, "POST", "/api/v1/auth/login", int(os.environ.get("PROBE_LOGIN_N","5")), json={"email": EMAIL, "password": PASSWORD})
        c.headers["Authorization"] = f"Bearer {tok}"
        me = (await c.get("/api/v1/auth/me")).json(); results["role"] = me.get("role")
        # discover ids
        ids = {}
        def first_id(payload):
            if isinstance(payload, dict):
                for k in ("data", "items", "results"):
                    if isinstance(payload.get(k), list) and payload[k]: return payload[k][0].get("id")
                if "id" in payload: return payload["id"]
            if isinstance(payload, list) and payload: return payload[0].get("id")
            return None
        for key, path in {"session_id": "/api/v1/sessions", "report_id": "/api/v1/reports", "alert_id": "/api/v1/alerts",
                          "patient_id": "/api/v1/patients", "notification_id": "/api/v1/notifications", "log_id": "/api/v1/audit-logs",
                          "complaint_id": "/api/v1/complaints", "user_id": "/api/v1/admin/users"}.items():
            try:
                rr = await c.get(path, params={"limit": 5}); ids[key] = first_id(rr.json()) if rr.status_code == 200 else None
            except Exception as e:
                ids[key] = None
        results["ids_found"] = {k: bool(v) for k, v in ids.items()}
        for path in sorted(spec["paths"]):
            ops = spec["paths"][path]
            if "get" not in ops: continue
            op = ops["get"]
            url = path; skip = None
            for seg in [s for s in path.split("/") if s.startswith("{")]:
                name = seg.strip("{}")
                if ids.get(name): url = url.replace(seg, str(ids[name]))
                else: skip = f"no id for {name}"
            if skip: results["skipped"][f"GET {path}"] = skip; continue
            params = {}
            for p in op.get("parameters", []):
                if p.get("in") != "query": continue
                nm = p["name"]
                if p.get("required") or nm in ("limit", "page_size"):
                    if nm in DEFAULTS: params[nm] = DEFAULTS[nm]
                    elif p.get("required"): skip = f"required param {nm} unknown"
            if skip: results["skipped"][f"GET {path}"] = skip; continue
            n = 5 if path.endswith("/pdf") else (3 if "research" in path else N)
            try:
                results["endpoints"][f"GET {path}"] = await timed(c, "GET", url, n, params=params)
            except Exception as e:
                results["skipped"][f"GET {path}"] = f"error {type(e).__name__}: {e}"
        # concurrency: 20 parallel list requests
        t0 = time.perf_counter()
        rs = await asyncio.gather(*[c.get("/api/v1/sessions", params={"limit": 20}) for _ in range(20)])
        results["concurrency_20x_sessions_wall_ms"] = round((time.perf_counter()-t0)*1000, 1)
        results["concurrency_20x_sessions_codes"] = {r.status_code: 1 for r in rs}.keys().__len__() and sorted({r.status_code for r in rs})
    if sampler:
        sampler.stop = True; sampler.join(timeout=1)
        results["rss_mb"] = {"min": round(min(sampler.samples),1), "peak": round(max(sampler.samples),1), "samples": len(sampler.samples)}
    out = os.path.join(S, f"perf_api_{LABEL}.json"); json.dump(results, open(out, "w"), indent=1, ensure_ascii=False)
    print(f"role={results.get('role')} rss={results.get('rss_mb')} concurrency20={results.get('concurrency_20x_sessions_wall_ms')}ms")
    print(f"{'endpoint':52s} {'n':>3s} {'p50':>8s} {'p95':>8s} {'max':>8s} codes")
    for k, v in results["endpoints"].items():
        print(f"{k:52s} {v['n']:3d} {v['p50_ms']:8.1f} {v['p95_ms']:8.1f} {v['max_ms']:8.1f} {v['codes']}")
    for k, v in results["skipped"].items(): print(f"SKIP {k}: {v}")
    print("saved", out)

asyncio.run(main())
