# NagarVault

An air-gapped, privacy-first civic data operating layer for municipal intelligence.
Ingest → enrich → warehouse → ask. All on one cluster, no data leaves the server room.

> **Start here: [`AGENTS.md`](AGENTS.md)** — the authoritative operating guide for engineers and
> autonomous agents alike. This README is only the landing page.

## What it is

NagarVault ingests raw civic events (citizen complaints, traffic, water sensors, health camps, EV
bus telemetry) through a Kafka backbone, enriches them into a PostgreSQL warehouse, and lets
authorized municipal officers query it in natural language — answered by locally-hosted small
language models with schema-aware RAG. Every SQL query passes AST validation, role-based access
control, and a PII denylist before touching data, and every attempt is audited.

## Documentation

| Document | Purpose |
|---|---|
| [AGENTS.md](AGENTS.md) | Entry point: invariants, system map, agent protocol |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Flows, endpoint/topic/storage registries, topology |
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | Layout, naming, config precedence, frozen port registry |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, JWT chain, RBAC, secrets, network policy |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Bootstrap, deploy, seed, backup/restore, troubleshooting |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture decision record (ADR) log |
| [docs/PHASES.md](docs/PHASES.md) | 11-phase implementation plan with isolation + rollback rules |
| [docs/manifests/exemplars/](docs/manifests/exemplars/README.md) | Canonical Kubernetes reference manifests |

## Tech stack

- **Runtime:** Kubernetes (k3s reference distribution) — declarative manifests, GitOps with
  Argo CD, no Docker Compose in the deployment path (transition plan: [docs/PHASES.md](docs/PHASES.md))
- **Data plane:** PostgreSQL (CloudNativePG), Kafka (Strimzi, KRaft), MinIO, Redis, Qdrant, Ollama
- **Backend services:** FastAPI (Python) ×5 + Express (Node) ingestion gateway
- **AI:** Qwen3 1.7B (NL → SQL) + BGE-M3 (embeddings), fully local via Ollama
- **Frontends:** Next.js officer console; Vite mock-data injector (dev tool)

## Quick orientation

```text
Browser → frontend :3001 → authService :4000 (JWT session)
                        → slmService :4004 → Qdrant + Ollama + queryService :4003 → PostgreSQL
Files   → ingestion :3000 → MinIO presigned PUT → Kafka → enrichWorker → PostgreSQL
Ops     → adminService :4001 → health, audit logs, DLQ, vector re-sync
```

## Deployment status

Phase 0 (documentation suite) is complete. Cluster bring-up proceeds phase by phase per
[docs/PHASES.md](docs/PHASES.md). Until Phase 10 completes, the frozen `docker-compose*.yml` files
remain the only runnable path for local experimentation — they are legacy, unsupported, and slated
for deletion at cutover (ADR-004).
