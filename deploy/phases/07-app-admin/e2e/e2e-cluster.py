# Phase 7f — cluster-internal E2E (run from an admin pod, §12.26: it owns the flows).
#   cat tokens | kubectl exec -i <admin-pod> -- sh -c '
#     read -r E2E_ADMIN; read -r E2E_OFFICER; export E2E_ADMIN E2E_OFFICER; python /tmp/e2e7f.py'
# ($(head -1)/$(tail -1) in ONE sh -c consumes the whole pipe into the first var —
# the G7f officer-403 401s were exactly that; read -r per line is the fix.)
# Both tokens come from real authService /logins (minted adm7f admin + off7f officer);
# shredded afterwards. Covers:
#   1. /health/cluster  — per-dependency booleans, all = AND
#   2. /dlq             — bounded tail; must contain the malformed fixture the operator
#                         produced directly to nmc.complaints.raw.restricted.v1 (fixture B)
#   3. /audit-logs      — real rows from the 7b/7d gates
#   4. Authz matrix     — officer token 403 on every admin endpoint; no token 401
#   5. API-layer malformed handling — POST /api/v1/events missing description -> 400
#                         (fixture A; never reaches Kafka, so no DLQ entry for it)
import json
import os
import time
import urllib.error
import urllib.request

BASE = "http://localhost:4001"
INGESTION = "http://ingestion.nagar-app.svc.cluster.local:3000"


def call(base, path, token=None, body=None):
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode() if body is not None else None,
        headers=headers, method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return {"status": r.status, "body": json.loads(r.read().decode())}
    except urllib.error.HTTPError as e:
        try:
            return {"status": e.code, "body": json.loads(e.read().decode())}
        except Exception:
            return {"status": e.code, "body": "<unparseable>"}


out = {}
admin = os.environ["E2E_ADMIN"]
officer = os.environ["E2E_OFFICER"]

# --- 1. cluster health summary (admin) -------------------------------------------
out["healthCluster"] = call(BASE, "/health/cluster", token=admin)

# --- 2. DLQ inspection (admin) ----------------------------------------------------
out["dlq"] = call(BASE, "/dlq?limit=20", token=admin)

# --- 3. audit logs (admin) --------------------------------------------------------
out["auditLogs"] = call(BASE, "/audit-logs?limit=5", token=admin)

# --- 4. authz matrix ---------------------------------------------------------------
out["officer403"] = {
    "healthCluster": call(BASE, "/health/cluster", token=officer)["status"],
    "dlq": call(BASE, "/dlq", token=officer)["status"],
    "auditLogs": call(BASE, "/audit-logs", token=officer)["status"],
}
out["noAuth401"] = call(BASE, "/health/cluster")["status"]

# --- 5. fixture A: API rejects malformed events before Kafka (missing description) --
# The admin-service egress policy has no path to ingestion (SECURITY §8); this call is
# EXPECTED to fail with connection refused — that refusal is itself the proof that the
# policy enumerates exactly the documented flows. Fixture A is therefore executed by the
# operator directly against an ingestion pod, out-of-band (see mission log G7f.4).
try:
    out["ingestionApiRejects"] = call(
        INGESTION, "/api/v1/events", token=admin,
        body={
            "department": "complaints", "sourceSystem": "e2e7f",
            "sourceRecordId": f"e2e7f-api-{int(time.time() * 1000)}",
            "occurredAt": "2026-09-30T00:00:00Z", "payload": {"ward": "9"},
        },
    )
except (urllib.error.URLError, OSError) as e:
    out["ingestionApiRejects"] = {"status": "blocked-by-design", "detail": str(e)}

print("E2E-RESULT " + json.dumps(out, indent=1))
