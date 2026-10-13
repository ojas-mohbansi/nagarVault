# NagarVault

An air-gapped, privacy-first civic data operating layer for municipal intelligence —
ingest → enrich → warehouse → ask, all on one cluster; no data leaves the server room.
Start with [`AGENTS.md`](AGENTS.md), the authoritative operating guide (index for `docs/`).

Raw civic events (complaints, traffic, water sensors, health camps, EV bus telemetry) flow
through Kafka into a PostgreSQL warehouse; officers query in natural language via locallyhosted small models with schema-aware RAG, behind AST validation, RBAC, and a PII denylist.

## Tech stack

- **Runtime:** Kubernetes (k3s), GitOps with Argo CD — no Docker Compose in the deployment path
- **Data plane:** PostgreSQL (CloudNativePG), Kafka (Strimzi, KRaft), MinIO, Redis, Qdrant, Ollama
- **Services:** FastAPI (Python) ×5 + Express (Node) ingestion gateway
- **AI:** Qwen3 1.7B (NL → SQL) + BGE-M3 (embeddings), fully local via Ollama
- **Frontends:** Next.js officer console; Vite mock-data injector (dev tool)

## Quick orientation

```text
Browser → frontend :3001 → authService :4000 (JWT session)
                        → slmService :4004 → Qdrant + Ollama + queryService :4003 → PostgreSQL
Files   → ingestion :3000 → MinIO presigned PUT → Kafka → enrichWorker → PostgreSQL
Ops     → adminService :4001 → health, audit logs, DLQ, vector re-sync
```

All ten phases are shipped through Argo CD on the k3d substrate (ADR-013); per-phase ledger:
[`docs/PHASES.md`](docs/PHASES.md).
