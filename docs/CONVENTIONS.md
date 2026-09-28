# Conventions — NagarVault

> Normative. Agents and reviewers enforce this file. Hub: [AGENTS.md](../AGENTS.md).

## 1. Repository layout

```
/                    repo root — AGENTS.md is the entry point; no code lives here
agentic/             (reserved) agent-facing automation entrypoints
adminService/        FastAPI admin API (ports 4001)
authService/         FastAPI auth API (4000); includes seed_admin.py
enrichWorker/        Python Kafka consumer; migrations/ holds idempotent SQL
frontend/            Next.js officer console (3001)
nagar-vault-backend/ Express ingestion API (3000) — tests: `npm test`, `npm run check`
nagar-vault-ui/      Vite mock-data injector (5173) — dev tool
queryService/        FastAPI SQL execution + RBAC (4003)
schemaIndexer/       Qdrant schema indexer (4005); index.py + schema_docs.json
slmService/          FastAPI NL→SQL service (4004)
docs/                this documentation suite
docs/manifests/exemplars/   canonical reference YAML (read-only in review; evolves via ADR)
deploy/              (Phase 1+) live manifest tree — the only source of cluster truth
  phases/NN-name/    one directory per phase; phase boundaries are directory boundaries
docker-compose*.yml  FROZEN (AGENTS.md I-10). Delete in Phase 10.
**/Dockerfile        FROZEN per-service images. Delete in Phase 10.
```

## 2. Naming rules

| Object | Rule | Example |
|---|---|---|
| Directories | snake_case, match service directory name | `queryService/` |
| k8s metadata.name | lowercase RFC-1123, kebab-case | `nagar-auth-service` |
| Image prefix | `registry.nagar.internal:5000/nagar-<service>` | `nagar-auth-service` |
| Kafka topics | `<dept>.<entity>.raw[.restricted].v<N>` | `nmc.complaints.raw.restricted.v1` |
| Buckets | lowercase kebab | `raw-sensitive-media` |
| Qdrant collection | snake_case | `nagar_schema` |
| DB tables | snake_case plural | `water_sensor_readings` |
| Secrets (keys) | SCREAMING_SNAKE, mirror env var names | `jwtSecret` key holds `JWT_SECRET` value |
| ADRs | `ADR-###` sequential, never renumbered | `ADR-007` |

## 3. Configuration precedence

Every component resolves configuration in exactly this order; later wins:

1. **In-code default** (documented in the service's own README/env example)
2. **SealedSecret value** deployed into the namespace (the production source)
3. **Phase-specific overlay** (`deploy/phases/NN/overlays/*`)

Rules:
- Env var names are frozen once shipped (e.g. `JWT_SECRET`, `DATABASE_URL`, `OLLAMA_URL`,
  `BOOTSTRAP_SERVER`, `KAFKA_BROKERS`, `MINIO_*`, `REDIS_URL`, `QDRANT_URL`, `QUERY_SERVICE_URL`).
- Hostnames in K8s use full Service DNS:
  `postgres-rw.nagar-platform.svc.cluster.local:5432`,
  `kafka-bootstrap.nagar-platform.svc.cluster.local:29092`,
  `minio.nagar-platform.svc.cluster.local:9000`,
  `ollama.nagar-platform.svc.cluster.local:11434`,
  `qdrant.nagar-platform.svc.cluster.local:6333`,
  `redis.nagar-platform.svc.cluster.local:6379`.
- Compose-only hostnames (`kafka:29092`, `postgres:5432`, `minio:9000`, `redis:6379`) are legacy
  and appear only inside frozen files.

## 4. Port registry (frozen — AGENTS.md I-6)

| Port | Owner | Exposure (target state) |
|---|---|---|
| 3000 | ingestion API | ingress `/api` (internal) |
| 3001 | frontend | ingress `/` (public edge) |
| 4000 | authService | ingress `/auth` (public edge) |
| 4001 | adminService | ingress `/admin` (internal, admin JWT) |
| 4003 | queryService | cluster-internal only |
| 4004 | slmService | cluster-internal only |
| 4005 | schemaIndexer | cluster-internal only |
| 5173 | vault-ui injector | dev overlay only, never exposed at edge |
| 5432 | PostgreSQL | namespace + nagar-app only |
| 6333 / 6334 | Qdrant HTTP / gRPC | namespace + nagar-app (6333) only |
| 6379 | Redis | nagar-platform + ingestion only |
| 9000 | MinIO S3 API | namespace + edge upload route (browser PUT) |
| 11434 | Ollama | namespace + nagar-app only |
| 29092 | Kafka listeners | namespace + nagar-app only |

Adding or changing a port = ADR. Client code and manifests must reference the registry, not memory.

## 5. Label schema (mandatory on every manifest)

```yaml
metadata.labels:
  app.kubernetes.io/name: <service>        # e.g. nagar-auth-service
  app.kubernetes.io/part-of: nagarvault
  app.kubernetes.io/component: <api|worker|ui|database|broker|storage|ai|edge|init>
  app.kubernetes.io/managed-by: argocd
  nagar.io/phase: "NN"                      # owning phase, two digits
  nagar.io/tier: "<0-9>"                    # startup tier, ARCHITECTURE.md §4.4
```

Selectors must use `app.kubernetes.io/name` + `app.kubernetes.io/component` only (stable keys).

## 6. Git conventions

- Branch names: `phase/NN-short-name` or `fix/<slug>`.
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`) — e.g.
  `feat(phase-5): cnpg cluster with wal backups`.
- One phase per branch; a branch must not mix phases.
- Manifest changes never mix with application-code changes in the same commit.

## 7. Documentation conventions

- Every doc links upward to [AGENTS.md](../AGENTS.md) and sideways where a contract is referenced.
- Facts about the *current* runtime are labeled; facts about the *target* are labeled "Phase N+".
- New non-obvious decisions require an ADR in [DECISIONS.md](DECISIONS.md) *before* the PR that
  implements them. ADRs are immutable once accepted — supersede, never edit.
- Every new env var, port, topic, bucket, or table must be added to the relevant registry in this
  suite in the same change.

## 8. Code conventions (existing, keep)

- Python services: FastAPI + uvicorn, requirements.txt (no lockfile churn without ADR), snake_case.
- Node ingestion: ESM, zod-validated request schemas, pino structured logs, request IDs on errors.
- Frontend: Next.js app router; never call services cross-origin except through the configured
  `NEXT_PUBLIC_*` base URLs.
- No new runtime dependency without an ADR-007-style entry (see DECISIONS.md).
