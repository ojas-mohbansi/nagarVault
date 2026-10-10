# NagarVault — Links & Credentials

> Live cluster: k3d substrate, 16/16 Argo Applications Synced/Healthy.
> Host-facing ports are sequential on the 36000 series (36000–36004).
> Populated 2026-10-10 from a live probe pass.

---

## How to open these in a browser

**Edge / officer console (HTTPS).** Open `https://k3d-nagar.localhost:36000/` directly in a browser.
- `k3d-nagar.localhost` resolves to 127.0.0.1 automatically (no hosts-file entry needed).
- The TLS cert is self-signed (CA = `nagar-edge-ca`, CN `k3d.nagar.internal`).
  The browser shows a "Your connection is not private / Self-signed certificate" warning.
  Click **Advanced → Proceed to k3d-nagar.localhost (unsafe)** to continue.
  The cert's SAN includes `k3d-nagar.localhost`, so there is no name mismatch — just an untrusted CA.
- The Traefik edge route matches `Host(k3d.nagar.internal) || Host(k3d-nagar.localhost)` and TLS
  terminates on the `edge-tls` secret, so the browser's Host header and the cert both line up.

**Grafana, Loki, Prometheus, Alertmanager (HTTP).** Open the `http://127.0.0.1:PORT` URLs directly.
No TLS, no flags, no resolve needed.

---

## Links (sequential ports 36000–36004)

| # | Last digit | Service | URL to open in browser | What you get |
|---|---|---|---|---|
| 0 | 0 | Edge / Officer Console (frontend) | `https://k3d-nagar.localhost:36000/` | Login page → dashboard → NL chatbot. Title: "NagarVault — Officer Console". |
| 1 | 1 | Grafana | `http://127.0.0.1:36001` | Dashboards console (login required). `/api/health` → `{"database":"ok"}`. |
| 2 | 2 | Loki | `http://127.0.0.1:36002` | Log query UI. `/ready` → 200. |
| 3 | 3 | Prometheus | `http://127.0.0.1:36003` | Metrics console. `/-/ready` → 200. |
| 4 | 4 | Alertmanager | `http://127.0.0.1:36004` | Alert console. `/api/v2/alerts` → 200 (empty array = no alerts firing). |

**Edge sanity-check endpoints** (open in browser address bar or use the console):
- `https://k3d-nagar.localhost:36000/auth/` → `{"status":"ok","service":"authService"}` (200, no auth needed)
- `https://k3d-nagar.localhost:36000/admin/health/cluster` → `{"db":true,"kafka":true,"schemaIndexer":true,"all":true}` (200, admin auth needed)

---

## Test accounts (smoke-test only — created during this session)

These exist in the running Postgres, not in git (users are data, not manifests — I-3).

| Username | Password | Role | Notes |
|---|---|---|---|
| `admin-smoke` | `nagar-smoke-878bf78f` | admin | Admin JWT; `/ask` blocked by table-rbac (admin has no warehouse tables — correct). Can create users via `POST /auth/create`. |
| `officer-ask` | `nagar-officer-ask-123` | nmc_officer | Can `/ask` against warehouse tables (nmc_complaints, traffic_events, water_sensor_readings, ev_bus_telemetry). |

- officer-ask verified: `/ask "how many complaints?"` → `{"sql":"SELECT COUNT(event_id) FROM nmc_complaints","rows":[{"count":15}],"row_count":1}`.

**Login flow (browser):** open `https://k3d-nagar.localhost:36000/`, enter username + password.
The session cookie (`session_token`, HttpOnly, Secure, SameSite=lax, 1h) is set by authService
through the edge and relayed to the BFF for subsequent requests.

**To create more users (admin only):** `POST https://k3d-nagar.localhost:36000/auth/create`
with JSON body `{"username":"...","password":"...","role":"nmc_officer"|"ROLE_HEALTH_OFFICER"|"admin"}`
and the admin session cookie. Role literal for health officers is `ROLE_HEALTH_OFFICER`.

---

## NL chatbot (`/ask`) — current state

- **Working end-to-end for authorized roles.** The full chain:
  edge → BFF (frontend :3001) → slmService :4004 → Qdrant (schema RAG) → Ollama (Qwen3 1.7B) →
  queryService :4003 (RBAC) → PostgreSQL.
- **Qdrant was reindexed** during this session (`POST http://schema-indexer:4005/reindex` →
  `{"upserted":40,"points_count":40}`) after it returned empty/corrupt and caused a 503 on `/ask`.
  If `/ask` 503s again, the fix is the same reindex. Recovery path: OPERATIONS §12.33 / ADR-028.
- **Admin users cannot query warehouse tables** (table-rbac, SECURITY §3) — that's the design, not a bug.

---

## Ingestion API (`/api`) — current state

- Pods Running 1/1, Service endpoints populated, edge route `/api` → ingestion :3000 live.
- Requires a session cookie. Unauthenticated → 401 `{"detail":"missing session"}`.
- Example: `POST https://k3d-nagar.localhost:36000/api/v1/uploads/presign` with cookie →
  presigned MinIO PUT URL (or 401 without cookie).

---

## For operators: starting the port-forwards

These forwards are per-shell and die with their parent. To re-create them:

```bash
export KUBECONFIG='C:/Users/styli/AppData/Local/Temp/kubeconfig'

kubectl -n nagar-system port-forward --address 127.0.0.1 svc/traefik-edge 36000:443 &
kubectl -n nagar-observability port-forward --address 127.0.0.1 svc/nagar-grafana 36001:3300 &
kubectl -n nagar-observability port-forward --address 127.0.0.1 svc/nagar-loki 36002:3100 &
kubectl -n nagar-observability port-forward --address 127.0.0.1 svc/nagar-prometheus 36003:9090 &
kubectl -n nagar-observability port-forward --address 127.0.0.1 svc/nagar-alertmanager 36004:9093 &
```

Kill them when done: `taskkill //F //IM kubectl.exe` (Windows) or kill the kubectl PIDs.
Leak check per OPERATIONS §12.34: `tasklist //FI "IMAGENAME eq kubectl.exe"`.

---

## Sealed secrets (reference only — values never plaintext in git)

| Secret | Namespace | Keys |
|---|---|---|
| nagar-jwt | nagar-app | jwtSecret |
| nagar-minio | nagar-app | accessKey, secretKey |
| nagar-postgres-app | nagar-app | databaseUrl |
| nagar-minio-server | nagar-platform | accessKey, secretKey, mcHostLocal |
| nagar-postgres-bootstrap | nagar-platform | username, password |

Sealed with `kubeseal --cert` against the Sealed Secrets controller cert.
Only the encrypted blobs live in `deploy/phases/*/secrets/`.
