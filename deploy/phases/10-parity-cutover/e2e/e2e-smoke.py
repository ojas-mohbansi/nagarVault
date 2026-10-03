# Phase 10 — OPERATIONS §11 post-deploy smoke test, scripted (PHASES.md Phase-10 entry gate).
#
#   NV_ADMIN_USER / NV_ADMIN_PASSWORD       seeded admin — from the operator vault (§5)
#   NV_OFFICER_USER / NV_OFFICER_PASSWORD   an officer account (step 5 must NOT be admin:
#                                           admin /ask is denied by table-rbac, SECURITY §3)
#   NV_EDGE_PORT                            local tunnel port (default 4431)
#   NV_ENRICH_TIMEOUT                       seconds to wait for the worker row (default 60)
#
#   python deploy/phases/10-parity-cutover/e2e/e2e-smoke.py
#
# This driver owns the whole §11 invocation note (proved Phase 8, G8.7 / §12.34): it spawns the
# traefik-edge port-forward, polls until the edge answers, runs all six steps over TLS through
# that ONE tunnel, and kills the tunnel on exit — a cross-command forward dies with its parent
# shell, so spawn/poll/prove/kill must live in one process. It replaces curl's `-k` with an
# unverified TLS context (the internal CA is not in the host trust store) and `--ssl-no-revoke`
# with nothing at all (Python does not do schannel revocation checks); the `--resolve` trick
# becomes a literal Host: header, because Traefik routes on Host (ADR-024 §5).
#
# No secret is printed: passwords are read from the environment, the session token is taken from
# Set-Cookie and never logged, and the officer/admin credentials only ever appear in request
# bodies. Exit code 0 iff all six steps pass; markers are `SMOKE-<n>-OK` and `SMOKE-RESULT`.
import base64
import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import time

HOST = os.environ.get("NV_EDGE_HOST", "k3d.nagar.internal")
PORT = int(os.environ.get("NV_EDGE_PORT", "4431"))
ENRICH_TIMEOUT = int(os.environ.get("NV_ENRICH_TIMEOUT", "60"))

ADMIN_USER = os.environ.get("NV_ADMIN_USER")
ADMIN_PASSWORD = os.environ.get("NV_ADMIN_PASSWORD")
# Officer credentials are OPTIONAL: when absent, step 5 mints its own officer through the
# admin-gated POST /auth/create (the precedent every prior gate used — G7g.3, G8R.5). The
# username carries the run's timestamp so re-runs never collide with a prior password (I-2).
OFFICER_USER = os.environ.get("NV_OFFICER_USER")
OFFICER_PASSWORD = os.environ.get("NV_OFFICER_PASSWORD")

PG_NS = "nagar-platform"
PG_POD = "postgres-1"
PG_HOST = "postgres-rw.nagar-platform.svc.cluster.local"

# curl -k equivalent: the internal CA is issued by the cluster, not by a host-trusted root.
TLS = ssl._create_unverified_context()
_forward = None
_passed = 0
_failed = 0


# The edge's TLSOption sets `sniStrict: true`, and Python only sends an SNI extension for a
# HOSTNAME — never for a literal IP (RFC 6066 §3). Connecting to "127.0.0.1" would therefore
# drop the SNI and Traefik would not match the router. So we keep the real hostname for SNI and
# Host, and point only the DNS lookup at the local tunnel — the same thing curl's --resolve does.
_real_getaddrinfo = socket.getaddrinfo


def _tunnel_resolver(host, port, *args, **kwargs):
    if host == HOST:
        host = "127.0.0.1"
    return _real_getaddrinfo(host, port, *args, **kwargs)


def log(msg):
    print(msg, flush=True)


def check(n, ok, label, detail=""):
    global _passed, _failed
    if ok:
        _passed += 1
        log(f"SMOKE-{n}-OK  {label}" + (f"  {detail}" if detail else ""))
    else:
        _failed += 1
        log(f"SMOKE-{n}-FAIL {label}" + (f"  {detail}" if detail else ""))
    return ok


def call(method, path, body=None, token=None, cookie=None, timeout=30):
    """One request through the tunnel. Returns (status, text, set_cookies, headers)."""
    conn = http.client.HTTPSConnection(HOST, PORT, context=TLS, timeout=timeout)
    headers = {"Host": HOST, "Accept": "application/json", "Connection": "close"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cookie:
        headers["Cookie"] = cookie
    try:
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8", "replace")
        set_cookies = resp.headers.get_all("Set-Cookie") or []
        return resp.status, text, set_cookies, dict(resp.headers)
    finally:
        conn.close()


def session_cookie(set_cookies):
    """session_token=...; Path=/; ...  ->  'session_token=...' (value never logged)."""
    for raw in set_cookies:
        if raw.startswith("session_token="):
            return raw.split(";", 1)[0]
    return None


def cookie_attrs(set_cookies):
    """The attribute list of the session cookie, with the value redacted.

    NOTE: read the attributes from the ORIGINAL Set-Cookie list, never from
    dict(resp.headers) — that mapping keys on the wire case ("Set-Cookie") and keeps only the
    first value, so `.get("set-cookie")` silently returns None and the assertion below would
    fail on a perfectly good response (found live in G10.1: the cookie did carry Secure).
    """
    for raw in set_cookies:
        if raw.startswith("session_token="):
            parts = [p.strip() for p in raw.split(";")[1:]]
            return "session_token=<redacted>" + ("; " + "; ".join(parts) if parts else "")
    return "<no session cookie>"


def spawn_tunnel():
    global _forward
    _forward = subprocess.Popen(
        ["kubectl", "-n", "nagar-system", "port-forward", "svc/traefik-edge",
         f"{PORT}:443", "--address", "127.0.0.1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 40
    while time.time() < deadline:
        if _forward.poll() is not None:
            return False  # tunnel process died (port taken, cluster gone)
        try:
            # Poll on `/` — deliberately NOT /auth, whose edge rate limiter (10/min, burst 20)
            # would be drained by the poll loop before step 2 gets a turn.
            status, _, _, _ = call("GET", "/", timeout=5)
            if status in (200, 307):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _secret(key):
    """Read one key of the app-role Secret (G5.2's credential contract). Never logged."""
    raw = subprocess.run(
        ["kubectl", "-n", PG_NS, "get", "secret", "nagar-postgres-bootstrap",
         "-o", f"jsonpath={{.data.{key}}}"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return base64.b64decode(raw).decode()


def db_scalar(sql, timeout=30):
    """Run one scalar query as the application role, from inside the Postgres pod."""
    out = subprocess.run(
        ["kubectl", "-n", PG_NS, "exec", PG_POD, "-c", "postgres", "--",
         "env", f"PGPASSWORD={_secret('password')}", "psql",
         "-h", PG_HOST, "-U", _secret("username"), "-d", "nagardb", "-tAc", sql],
        capture_output=True, text=True, timeout=timeout,
    )
    if out.returncode != 0:
        raise RuntimeError(f"psql failed: {out.stderr.strip()[:200]}")
    return out.stdout.strip()


def main():
    global _forward
    if not (ADMIN_USER and ADMIN_PASSWORD):
        log("usage: NV_ADMIN_USER and NV_ADMIN_PASSWORD must be set (seeded admin, OPERATIONS §5);"
            " NV_OFFICER_USER/NV_OFFICER_PASSWORD are optional")
        return 2

    log(f"--- OPERATIONS §11 smoke, edge https://{HOST}:{PORT} (tunnel spawned here) ---")
    if not spawn_tunnel():
        log(f"SMOKE-RESULT: edge tunnel on 127.0.0.1:{PORT} never answered")
        return 1

    try:
        # ---- step 1: auth service answers over TLS -------------------------------
        status, text, _, _ = call("GET", "/auth/")
        ok = status == 200 and '"status":"ok"' in text and "authService" in text
        check(1, ok, "GET /auth/", f"HTTP {status} {text.strip()[:80]}")

        # ---- step 2: seeded admin login, Secure session cookie --------------------
        status, text, cookies, _ = call(
            "POST", "/auth/login",
            body={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        )
        cookie = session_cookie(cookies)
        attrs = cookie_attrs(cookies)
        check(2, status == 200 and cookie is not None and "Secure" in attrs
              and "HttpOnly" in attrs,
              "POST /auth/login (seeded admin)",
              f"HTTP {status} Set-Cookie: {attrs}")
        admin_token = cookie.split("=", 1)[1] if cookie else None
        if not admin_token:
            log("SMOKE-RESULT: no session — cannot continue")
            return 1

        # ---- step 4 measurement point: row count BEFORE the ingest ---------------
        count_before = int(db_scalar("SELECT COUNT(*) FROM nmc_complaints"))
        log(f"        nmc_complaints before ingest: {count_before}")

        # ---- step 3: ingest a JSON-only event, expect 202 + eventId -------------
        stamp = str(int(time.time()))
        status, text, _, _ = call(
            "POST", "/api/v1/events", token=admin_token,
            body={
                "department": "complaints",
                "sourceSystem": "ops-smoke",
                "sourceRecordId": f"p10-smoke-{stamp}",
                "occurredAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "payload": {"description": "Phase-10 OPERATIONS §11 smoke event"},
            },
        )
        try:
            body = json.loads(text)
        except Exception:
            body = {}
        ok = status == 202 and body.get("eventId", "").startswith("evt-") and body.get("topic")
        check(3, ok, "POST /api/v1/events (JSON only)",
              f"HTTP {status} {body.get('topic', '?')} {body.get('eventId', '?')}")
        if not ok:
            log("SMOKE-RESULT: ingest failed — downstream steps cannot pass")
            return 1

        # ---- step 4: the worker enriches it into the warehouse -------------------
        deadline = time.time() + ENRICH_TIMEOUT
        count_after = count_before
        while time.time() < deadline:
            count_after = int(db_scalar("SELECT COUNT(*) FROM nmc_complaints"))
            if count_after > count_before:
                break
            time.sleep(3)
        check(4, count_after > count_before,
              "enrich lands in PostgreSQL nmc_complaints",
              f"{count_before} -> {count_after}")

        # ---- step 5: ask, as an officer, through the console BFF -----------------
        # §11 writes "POST /ask via edge"; slmService is deliberately not edge-routed
        # (ADR-024 §5) and the console's own surface is the BFF route /api/ask
        # (ADR-023), which ADR-027 put back behind the edge. Admin is wrong here by
        # design: an admin ask is denied by table-rbac (SECURITY §3).
        officer_user, officer_password = OFFICER_USER, OFFICER_PASSWORD
        if not (officer_user and officer_password):
            import secrets
            officer_user = f"p10smoke-{stamp}"
            officer_password = secrets.token_urlsafe(18) + "!Aa1"  # never printed
            status, text, _, _ = call(
                "POST", "/auth/create", token=admin_token,
                body={"username": officer_user, "password": officer_password,
                      "role": "nmc_officer"},
            )
            log(f"        POST /auth/create (admin-gated) -> HTTP {status} {text.strip()[:90]}")
        status, text, cookies, _ = call(
            "POST", "/api/login",
            body={"username": officer_user, "password": officer_password},
        )
        officer_cookie = session_cookie(cookies)
        if status != 200 or not officer_cookie:
            check(5, False, "officer console login (POST /api/login)", f"HTTP {status}")
        else:
            # The question NAMES the table on purpose. A vague "how many complaints are in the
            # warehouse?" lets the model choose the table per sample: on the 2026-10-03 closure run
            # Qwen3 answered it with `SELECT COUNT(*) FROM health_camp_records WHERE media_bucket IS
            # NOT NULL`, which an nmc_officer is correctly denied (SECURITY §3 / ROLE_TABLES), so
            # step 5 failed 5/6 on a correct 403 while three other runs of the identical input
            # passed. Naming the table removes that per-sample choice and keeps the probe about the
            # ask PATH (edge -> BFF -> slmService -> queryService -> SQL + rows), which is what §11
            # step 5 tests. A bounded re-ask on a 403 was tried first and removed: the reword alone
            # answered on the first attempt in every run, so the retry was dead machinery.
            # The first ask after an idle period loads both models in Ollama (bge-m3 + qwen3),
            # which can outlast a tight client timeout; allow for the cold start and record the
            # body verbatim when it does not answer.
            status, text, _, _ = call(
                "POST", "/api/ask", cookie=officer_cookie, timeout=120,
                body={"question": "How many rows are in the nmc_complaints table?"},
            )
            try:
                ask = json.loads(text)
            except Exception:
                ask = {}
            ok = (status == 200 and isinstance(ask.get("sql"), str)
                  and "SELECT" in ask["sql"].upper() and "rows" in ask)
            check(5, ok, "POST /api/ask (officer, via edge + BFF)",
                  f"HTTP {status} sql={str(ask.get('sql'))[:60]!r} "
                  f"rows={len(ask.get('rows') or [])} role={ask.get('role')}"
                  + ("" if ok else f" body={text.strip()[:160]!r}"))

        # ---- step 6: admin cluster health ---------------------------------------
        status, text, _, _ = call("GET", "/admin/health/cluster", token=admin_token)
        try:
            health = json.loads(text)
        except Exception:
            health = {}
        check(6, status == 200 and health.get("all") is True,
              "GET /admin/health/cluster", f"HTTP {status} {text.strip()[:120]}")

        total = _passed + _failed
        log(f"SMOKE-RESULT: {_passed}/{total} PASS" + ("" if _failed == 0 else f" ({_failed} FAILED)"))
        return 0 if _failed == 0 and total == 6 else 1
    finally:
        if _forward is not None and _forward.poll() is None:
            _forward.terminate()
            try:
                _forward.wait(timeout=10)
            except Exception:
                _forward.kill()
        log("tunnel torn down")


if __name__ == "__main__":
    socket.getaddrinfo = _tunnel_resolver  # only the tunnel lookup is redirected
    sys.exit(main())
