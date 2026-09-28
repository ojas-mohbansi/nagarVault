# AGENTS.md — NagarVault Authoritative Operating Guide

> **Read this file first. It is the single entry point to the repository.**
> If any other document, README, script, or comment contradicts this file, this file wins.
> Last architecture review: 2026-09-29.

---

## 1. Mission

NagarVault is an **air-gapped, privacy-first civic data operating layer for municipal intelligence**.
It ingests raw civic events (citizen complaints, traffic, water sensors, health camps, EV bus telemetry)
through a Kafka backbone, enriches them into a relational warehouse, and lets authorized officers ask
natural-language questions that are answered by a locally-hosted small language model — no data ever
leaves the server room.

Two qualities define every decision in this repository:

1. **Zero-maintenance operations.** After deployment the platform heals, updates, backs up, and
   re-initializes itself from version-controlled state. No routine manual patching.
2. **Air-gap survivability.** Every image, chart, manifest, and model must be obtainable, verifiable,
   and deployable with **no internet access at runtime**.

---

## 2. The Invariants

Breaking one of these is a bug, regardless of what a reviewer or agent believes. Every manifest,
script, and code change is checked against these:

| # | Invariant | Practical meaning |
|---|---|---|
| I-1 | **Cluster state = git state.** | The cluster is reconciled from git by Argo CD. Never mutate live state with `kubectl edit`, `kubectl scale`, or imperative applies. The only sanctioned exceptions are in [OPERATIONS.md](docs/OPERATIONS.md) §9. |
| I-2 | **Everything is idempotent.** | Every Job, init container, and migration uses `IF NOT EXISTS` / `--if-not-exists` / checksum guards and is safe to re-run forever. |
| I-3 | **No plaintext secrets in git. Ever.** | Secrets are encrypted with Sealed Secrets at commit time. Only encrypted blobs live in the repo. See [SECURITY.md](docs/SECURITY.md) §6. |
| I-4 | **Every workload is production-shaped.** | Probes (readiness/liveness), resource requests+limits, NetworkPolicy, and (if replicas > 1) a PDB are mandatory. |
| I-5 | **Images are pinned by digest and verified.** | No `:latest`. Digest pinning plus SBOM, scan, and signature verification are enforced. See [SECURITY.md](docs/SECURITY.md) §7. |
| I-6 | **The port registry is frozen.** | Service ports 3000/3001/4000/4001/4003/4004/4005 and data-plane ports are a fixed contract, listed in [CONVENTIONS.md](docs/CONVENTIONS.md) §4. Changing one is an ADR. |
| I-7 | **Every alert links to a runbook.** | A Prometheus rule that fires without a runbook anchor is rejected. See [OPERATIONS.md](docs/OPERATIONS.md) §10. |
| I-8 | **Every decision has an ADR.** | Non-obvious architectural choices are recorded in [docs/DECISIONS.md](docs/DECISIONS.md) before the code lands. |
| I-9 | **Phases are isolated.** | A phase's manifests live under `deploy/phases/NN-name/`, touch nothing outside their subtree, and can be rolled back or skipped without harming other phases. See [PHASES.md](docs/PHASES.md). |
| I-10 | **Legacy files are frozen.** | `docker-compose.yml`, `docker-compose.dev.yml`, and all per-service `Dockerfile`s are frozen. Do not modify them. They are deleted in Phase 10. |
| I-11 | **Air-gap first.** | No manifest may pull from a cluster that cannot reach the internal registry at `registry.nagar.internal:5000`. |
| I-12 | **`kustomize build` always succeeds.** | Any manifest tree that fails `kustomize build` is broken, even if YAML-valid. |

---

## 3. One-paragraph system map

A browser user logs into the Next.js `frontend`, which obtains a JWT session from `authService`.
Files are uploaded directly to MinIO using presigned URLs minted by the Express `ingestion backend`,
which publishes validated event metadata to Kafka. The Python `enrichWorker` consumes Kafka topics,
normalizes payloads, and writes department tables in PostgreSQL. Officers query the warehouse through
`queryService` (sqlglot-validated SQL with per-role RBAC) or ask natural-language questions of
`slmService`, which retrieves schema context from Qdrant (indexed by `schemaIndexer`) and generates
SQL with a local Qwen3 1.7B model served by Ollama. `adminService` provides cluster health, audit
logs, DLQ inspection, and vector re-sync. Every hop is authenticated with the same JWT chain
(`iss=nagar-auth`, `aud=nagar-services`).

---

## 4. System components

| Component | Language | Port | Role | Deploy unit (target) |
|---|---|---|---|---|
| `authService` | Python/FastAPI | 4000 | Login, session cookies, user creation, JWT issuance | Deployment |
| `adminService` | Python/FastAPI | 4001 | Cluster health, audit logs, DLQ, vector re-sync | Deployment |
| ingestion backend (`nagar-vault-backend`) | Node/Express | 3000 | Presigned MinIO uploads, event validation, Kafka publish | Deployment |
| `frontend` | Next.js | 3001 | Officer console: login, dashboard, NL chatbot | Deployment |
| `queryService` | Python/FastAPI | 4003 | SQL execution with AST validation + RBAC | Deployment |
| `slmService` | Python/FastAPI | 4004 | NL → RAG → SQL → results | Deployment |
| `schemaIndexer` | Python/FastAPI | 4005 | Embeds schema docs into Qdrant (Job + API) | Job + Deployment |
| `enrichWorker` | Python | — (consumer) | Kafka → PostgreSQL enrichment | Deployment |
| `nagar-vault-ui` | Vite/React | 5173 | Mock-data injector (dev tool) | Deployment (dev overlay) |
| PostgreSQL | — | 5432 | Warehouse + auth + audit | CloudNativePG cluster |
| Kafka | — | 29092 | Event backbone (KRaft) | Strimzi |
| MinIO | — | 9000 | Object storage (media + backups) | StatefulSet |
| Redis | — | 6379 | Upload-intent + dedup store | StatefulSet |
| Qdrant | — | 6333/6334 | Vector store for schema RAG | StatefulSet |
| Ollama | — | 11434 | Local LLM serving | StatefulSet |

Full contracts: [ARCHITECTURE.md](docs/ARCHITECTURE.md). Port rules: [CONVENTIONS.md](docs/CONVENTIONS.md) §4.

---

## 5. Mandatory reading order

1. This file — invariants and system map.
2. [docs/PHASES.md](docs/PHASES.md) — where the project is going and what is safe to change now.
3. [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — naming, config precedence, port registry.
4. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — flows and contracts you must preserve.
5. [docs/SECURITY.md](docs/SECURITY.md) — boundaries you must not cross.
6. [docs/OPERATIONS.md](docs/OPERATIONS.md) — runbooks before you operate anything.
7. Topic-specific ADRs in [docs/DECISIONS.md](docs/DECISIONS.md).

Reading order is enforced by review. If your change touches data plane, read §4 of CONVENTIONS and
§3 of ARCHITECTURE twice — port mismatches and topic typos are the two most common failure modes.

---

## 6. Agent operating protocol

### 6.1 Before changing anything

1. Identify which phase your change belongs to in [docs/PHASES.md](docs/PHASES.md).
2. Confirm the phase is not frozen or already completed. Completed phases are reverted, not patched in place.
3. Read the ADRs in [docs/DECISIONS.md](docs/DECISIONS.md) relevant to your change.
4. If your change contradicts an ADR, **stop** and write a new ADR first (see CONVENTIONS §7).

### 6.2 Definition of done (every change)

- [ ] Invariants I-1 … I-12 hold.
- [ ] `kustomize build deploy/...` succeeds for every tree you touched.
- [ ] `kubectl apply --dry-run=client` passes for every new or modified manifest.
- [ ] Docs updated in the same change if behavior, ports, env vars, or procedures changed.
- [ ] ADR written if any choice was non-obvious.
- [ ] Phase charter's exit criteria (PHASES.md) met.
- [ ] No file outside your phase's declared subtree modified (I-9).

### 6.3 Never do

- Never modify or "improve" files declared frozen by I-10.
- Never introduce Helm charts, Ansible, Terraform, or imperative `kubectl` into deployment paths
  (ADR-002, ADR-003).
- Never reference an image without a digest pin.
- Never place a literal secret, password, token, or private key anywhere under version control.
- Never change a registered port, topic name, bucket name, or table name without an ADR.
- Never write documentation that states an aspiration as if it were reality. Document the target
  state in PHASES.md; document current behavior here and in ARCHITECTURE.md.
- Never delete another phase's manifests, even if they appear unused.

### 6.4 When something breaks mid-task

- Consult [docs/OPERATIONS.md](docs/OPERATIONS.md) §12 (troubleshooting matrix) before improvising.
- If the fix contradicts an invariant or ADR, stop and escalate to a human reviewer.
- A partial change is worse than no change: `git checkout -- <paths>` your work and report.

---

## 7. Current state of the world

**Phase 0 (this documentation suite) is complete. Phases 1–10 are not yet implemented.**

- The runtime substrate today is **Docker Compose** (frozen per I-10). The Kubernetes manifests in
  `docs/manifests/exemplars/` are canonical reference shapes, not yet applied anywhere.
- `docs/PHASES.md` §1 defines each phase's charter, exit criteria, rollback, and skip-consequence.
- Until Phase 10 completes, this repository is in **transition**: Compose remains the only runnable
  path, and that is intentional and documented.

---

## 8. Quick reference

- Doc index: §4 above and the table below.
- Port registry: [CONVENTIONS.md §4](docs/CONVENTIONS.md).
- Label schema: [CONVENTIONS.md §5](docs/CONVENTIONS.md).
- Secret handling: [SECURITY.md §6](docs/SECURITY.md).
- Rollback: [PHASES.md §3](docs/PHASES.md).

| Document | Purpose |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Flows, contracts, topology, dependency graph |
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | Layout, naming, ports, labels, config precedence |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, JWT chain, RBAC, secrets, policies |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Install, deploy, seed, backup, restore, troubleshoot |
| [docs/DECISIONS.md](docs/DECISIONS.md) | ADR log |
| [docs/PHASES.md](docs/PHASES.md) | 11-phase implementation plan with isolation rules |
| [docs/manifests/exemplars/](docs/manifests/exemplars/README.md) | Canonical reference YAML per workload |
