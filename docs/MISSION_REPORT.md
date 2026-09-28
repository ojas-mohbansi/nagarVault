# NagarVault Mission Report — Review, Fix & Verify Loop

Date: 2026-09-28
Scope: full repo (7 Python services, Node ingestion backend, 2 frontends, docker-compose, migrations, Ollama models)

## Result

`docker compose up --build -d` brings up all 19 containers; every service with a healthcheck reports
healthy and all six API services answer HTTP 200 (auth 4000, admin 4001, ingestion 3000, query 4003,
SLM 4004, schema-indexer 4005). The complete user journey was exercised end-to-end and passes:

- seed admin → login (cookie JWT) → `/profile`
- create `ROLE_HEALTH_OFFICER` user via admin `/create`; login; RBAC query of `health_camp_records` allowed
- JWT-protected `/query` with SELECT, PII column block, non-SELECT block, health-table role block
- every query/blocked query written to `audit_logs` (visible via admin `/audit-logs`)
- event POST → Kafka `water.sensors.raw.v1` → enrich-worker → `water_sensor_readings` row verified via SQL
- MinIO presigned upload → `PUT` of a real file → 200
- schema indexer → 40 chunks in Qdrant
- SLM `/ask`: NL question → generated SQL → query-service → result rows (verified for water and nmc)
- SLM RBAC enforcement: health question as admin correctly rejected 403 by the query service guard
- admin `/health/cluster`, `/dlq` (empty DLQ), `/audit-logs` all working

## Bugs found and fixed

### Code
1. **queryService — RBAC guard checked a nonexistent table (`health_records`)** (`queryService/main.py`).
   The health-officer restriction never matched, so any role could query `health_camp_records`.
   Fixed to the real table name; verified: admin gets 403, health officer succeeds.
2. **queryService — wrong DB driver dependency** (`queryService/requirements.txt`).
   SQLAlchemy 2 resolves `postgresql://` to psycopg 3, but `psycopg` was not installed — the service
   crash-looped at import. Added `psycopg[binary]==3.2.3` (kept pinned psycopg2 for other tooling).
3. **queryService — audit logging was entirely missing** (`queryService/main.py`).
   The `audit_logs` table existed and the admin service exposed `/audit-logs`, but nothing wrote rows.
   Added INSERTs for both ALLOWED and BLOCKED queries (audit failures never mask the original response).
4. **enrichWorker — ISO-8601 timestamp strings passed to asyncpg** (`enrichWorker/main.py`).
   Kafka events carry `"occurredAt": "...Z"` strings; asyncpg requires datetime objects, so every
   insert failed (`expected a datetime.date or datetime.datetime instance, got 'str'`) and offsets were
   never committed. Added `_ts()` ISO parser and applied it to all `occurredAt`/`receivedAt` arguments
   in all five insert handlers. Verified end-to-end Kafka→Postgres persistence.
5. **schemaIndexer — `await` on a non-coroutine bulk upload** (`schemaIndexer/index.py`).
   qdrant-client 1.19 makes `upload_points` synchronous, so `await` raised `TypeError`.
   Now called via `asyncio.to_thread` so the event loop is not blocked. Verified: 40 chunks indexed.
6. **slmService — `qwen3:2b` no longer exists in Ollama's registry** (`slmService/main.py`,
   `slmService/clients/ollama.py`, compose `ollama-pull`). Model pulls failed with "file does not
   exist". Switched to `qwen3:1.7b`. Verified NL→SQL answers with the model loaded.
7. **adminService — DLQ endpoint could hang** (`adminService/main.py`).
   `consumer_timeout_ms` with an async iterator raised `UnknownTopicOrPartitionError` when the DLQ
   topic didn't exist, and after topic creation the endpoint could still stall. Replaced with
   `getmany(timeout_ms=3000)` polling; also created the DLQ topic in `kafka-init`.
8. **kafka-init — entrypoint script could never run** (`docker-compose.yml`).
   The folded YAML scalar (`>`) collapsed newlines to spaces, producing
   `sh: syntax error: unexpected word (expecting "do")`. Rewritten as a literal block with a shell
   function; all 5 raw topics + DLQ created and verified via `kafka-topics.sh --list`.

### Compose / deployment
9. **Missing MinIO service** — `ingestion-backend` referenced `MINIO_ENDPOINT: minio`, but compose had
   no `minio` service. Added `minio` + `minio-init` (bucket creation for `raw-media` and
   `raw-sensitive-media`) and gated ingestion on `minio-init` completion.
10. **MinIO images vanished from Docker Hub** (MinIO removed free images in Sep 2025–2026; quay repos
    now private). Pinned working mirrors: `alpine/minio:RELEASE.2025-10-15T17-29-55Z` and
    `rancher/mirrored-minio-mc:RELEASE.2023-06-28T21-54-17Z`. The alpine image runs as a non-root
    user that cannot write a fresh root-owned volume — fixed with `user: "0:0"` and a busybox-`wget`
    healthcheck (image has no curl/mc).
11. **Healthcheck hardening** — added checks for qdrant (bash `/dev/tcp` HTTP probe), auth, query,
    ingestion (127.0.0.1 because container `localhost` resolves to IPv6 `::1` first, while Node binds
    IPv4), and fixed ingestion's IPv6-resolution failure. Removed obsolete top-level `version:` key.
12. **adminService DLQ topic mismatch** — default `complaints.dlq.topic` did not follow the project's
    `<dept>.<stream>.dlq.v1` naming and no producer created it. Standardized on
    `nmc.complaints.dlq.v1` and created it in `kafka-init`.
13. **Slow-container-network PyPI timeouts breaking builds** — all six Python Dockerfiles now use
    `pip --timeout 120`; builds are reproducible on flaky networks.

### Non-project blockers encountered (documented, not code)
- Docker Desktop self-update gutted the installation mid-session and had to be reinstalled after a
  reboot; the machine had **no Windows pagefile**, so commit exhaustion was killing Go-based helpers
  (`The paging file is too small`). An 8–32 GB pagefile was configured (script kept at
  `scripts/fix-pagefile.ps1`) and a post-reboot bootstrap script at `scripts/RESUME_MISSION.ps1`.

## Verification evidence

- All Python services compile (`python -m py_compile`); ingestion backend `node --check` + 5/5 tests.
- Frontend: Next.js production build OK; nagar-vault-ui Vite production build OK (after `npm install`).
- Live behavioral checks listed in the Result section were all executed against the running stack.

## Known remaining gaps (out of scope / flagged)

- `piiStorageWorker` is legacy dead code: it consumes a nonexistent `enrich-topic` and writes tables
  (`complaints`, `water_events`, `traffic_events`) that the current pipeline replaced. It is not part
  of docker-compose. Recommend deleting or rewriting to consume the `*.raw.v1` topics.
- Jaeger integration is disabled by SSRF allowlist by design (`jaeger` not in the compose stack).
- kafka-init topics use dots only (consistent) but mixed dot/underscore across producers would collide.
