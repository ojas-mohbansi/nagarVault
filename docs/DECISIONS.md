# Decisions (ADR Log) — NagarVault

> Status legend: Proposed | Accepted | Superseded by ADR-NNN.
> ADRs are immutable once Accepted — write a new ADR to supersede. Hub: [AGENTS.md](../AGENTS.md).

---

## ADR-001 — Kubernetes-native substrate on k3s; abandon Docker Compose
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 1

**Context.** The platform must run air-gapped on municipal hardware with zero-maintenance
operations. Compose provides no self-healing, no rollouts, no network segmentation, no secret
management, and no scheduling.

**Decision.** Treat the cluster as the runtime substrate. Standardize on **k3s** (single binary,
bundled Traefik + local-path storage, air-gap-friendly install) as the reference distribution, with
a portability contract: manifests may not use distro-specific features, so any CNCF-conformant
cluster works. Alternatives considered: k0s (equivalent, fewer batteries), RKE2 (heavier, CIS
hardening not currently required), kubeadm clusters (too much assembly).

**Consequences.** Model pulls, init jobs, CORS, TLS, and backups all move to cluster-native
mechanisms. Compose files freeze immediately and are deleted in Phase 10 (ADR-004).

---

## ADR-002 — Kustomize overlays; no Helm in the deployment path
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 1

**Decision.** All manifests are plain Kubernetes YAML composed with Kustomize bases/overlays.
Helm is banned from the deployment path (AGENTS.md §6.3).
**Rationale.** Templates hide drift from agents; raw YAML is diffable, reviewable, and exactly what
lands on the cluster. Where upstream components ship charts (CNPG, Strimzi operator install), we
vendor the rendered static manifests into `deploy/third_party/` and treat them as code.
**Consequences.** Upgrades of vendored operator manifests are explicit commits. No chart values
files. Slightly more YAML; dramatically more auditability.

---

## ADR-003 — GitOps with Argo CD: auto-sync, self-heal, prune
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 2

**Decision.** Argo CD (app-of-apps) is the only deployment mechanism. Auto-sync + self-heal + prune
on; no manual applies (AGENTS.md I-1, OPERATIONS §9 lists the only exceptions).
**Rationale.** Self-heal is what makes "zero maintenance" real: drift reverts itself, rollback is a
git operation, and the cluster's desired state is always readable from the repo.
**Consequences.** Every change — including a one-line env tweak — must flow through git/PR.

---

## ADR-004 — Compose & Dockerfiles: freeze now, delete at Phase 10
**Status:** Accepted · **Date:** 2026-09-29 · **Phases:** 0–10

**Decision.** `docker-compose.yml`, `docker-compose.dev.yml`, and per-service `Dockerfile`s are
frozen today (no edits, no fixes) and deleted in Phase 10 only after the parity checklist passes.
**Rationale.** Deleting early strands the only runnable path; keeping them mutable splits the
source of truth. A frozen, dated escape hatch is the safe middle.
**Consequences.** Bugs in Compose during transition are fixed by ignoring it, not patching it.

---

## ADR-005 — Operators only where self-healing pays for itself
**Status:** Accepted · **Date:** 2026-09-29 · **Phases:** 3–6

**Decision.** Use operators for **PostgreSQL (CloudNativePG)** and **Kafka (Strimzi)**. Run
**MinIO, Redis, Qdrant, Ollama** as plain StatefulSets.
**Rationale.** Operators are only justified when they automate something genuinely hard:
  - Postgres: replication, failover, WAL backup/restore — CNPG earns its keep outright.
  - Kafka: rebalancing, broker identity, cruise-control-scale ops — Strimzi earns its keep.
  - MinIO single-instance, Redis ephemeral, Qdrant single-node, Ollama with a model PVC: a
    StatefulSet + PVC + probes is already self-healing; an operator would add upgrade surface and
    air-gap weight for no recovery capability we need.
**Consequences.** Single-node MinIO/Qdrant are availability risks documented in ADR-006; both can
migrate to their operators later without app changes (services speak S3/HTTP, not operator APIs).

---

## ADR-006 — Single-node data plane accepted (with named mitigations)
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 3+

**Context.** Municipal deployments are single-node (or at best two-node) air-gapped servers.
**Decision.** Single replica for MinIO, Qdrant, Redis, and Kafka (KRaft single broker);
**two replicas** for PostgreSQL via CNPG where hardware allows; PDBs everywhere replicas > 1.
**Risk acceptance.** Kafka single-broker means topic data lives on one disk. Mitigations: source
systems can replay raw events; DLQ is inspectable; Postgres (the system of record) is replicated
and backed up. Scaling to multi-broker is a manifest-only change later.
**Consequences.** No false promises of HA in docs; runbooks state the real RPO (WAL ≈ 5 min).

---

## ADR-007 — Dependency addition policy
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** ongoing

**Decision.** Any new runtime dependency (image, pip/npm package) requires an ADR stating: purpose,
why no existing dependency suffices, maintenance status, license, and air-gap staging plan.
**Rationale.** Air-gapped systems fail on orphaned dependencies; every addition is a permanent
operational liability and must be justified once, in writing.

---

## ADR-008 — Single-tenant cluster; no external IdP; internal CA
**Status:** Accepted · **Date:** 2026-09-29 · **Phases:** 1, 8

**Decision.** One tenant (one municipality) per cluster. Authentication stays with the in-house
authService (no external IdP). TLS terminates at Traefik with certs from a cluster-internal CA via
cert-manager — no public ACME (air-gap makes Let's Encrypt impossible anyway).
**Consequences.** Trust distribution = distributing the internal CA root cert to workstations.
Federating an IdP later is an app-level change behind authService and needs a new ADR.

---

## ADR-009 — Port registry frozen; Service DNS names are the contract
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 1+

**Decision.** The existing ports (CONVENTIONS §4) are preserved verbatim through the migration —
Services select the same container ports the Compose stack used. Changes require an ADR and a
simultaneous update of every client (env vars + docs).
**Rationale.** Zero application-code change is the migration's prime directive; ports are the most
coupled surface.

---

## ADR-010 — Model provisioning via checksum-pinned init Job
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 6

**Decision.** Ollama models (`bge-m3`, `qwen3:1.7b`) are pulled by a Job using a pre-staged
models tarball verified by SHA-256 against a manifest committed to git; the Job populates the
Ollama PVC before the API becomes ready. No internet egress, no manual `exec`.
**Rationale.** Removes the one manual ritual from the legacy docs ("kubectl exec ... ollama pull")
and makes model state reproducible from git.

---

## ADR-011 — Observability stack: kube-prometheus-stack + Loki; Jaeger deferred
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 9

**Decision.** Metrics via Prometheus (kube-prometheus-stack), logs via Loki. Distributed tracing is
deferred: adminService already references a Jaeger URL, but no tracing pipeline exists today; the
env var stays inert until a tracing ADR is written. Alert rules require runbook anchors (I-7).

---

## ADR-012 — Policy enforcement with Kyverno; PSS `restricted`
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 1 (baseline) → 9 (full set)

**Decision.** Kyverno enforces: PSS restricted, mandatory label schema (CONVENTIONS §5), digest
pinning + cosign verification, registry allowlist, resource limits. Policy violations deny
admission and are reported, never auto-rewritten (mutate policies limited to defaults that are
safe, e.g. default NetworkPolicy).
**Rationale.** Kyverno policies are plain YAML readable by agents; no policy language to learn.
Alternatives (OPA/Gatekeeper) rejected: rego raises the review bar with no benefit here.

---

## ADR-014 — Git transport for the disposable substrate; Argo CD v3.5 settings facts
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 2

**Context.** ADR-003 makes Argo CD the only deployment mechanism; Argo reads desired state from
**git**, never from a host filesystem. The k3d-in-Docker network cannot reach host processes
(proven by probe: host git-daemon unreachable from pods), the owner forbids pushes to the origin
remote, and the cluster is disposable. Separately, Argo CD v3.5 removed
`Application.spec.source.kustomize.buildOptions` from the Application schema AND does not accept
a `--kustomize-build-options` repo-server flag (verified: `Error: unknown flag`); the supported
global override is the `argocd-cm` settings key `kustomize.buildOptions`.

**Decisions.**
1. **In-cluster git mirror, registry staging model.** The bare repo (at the mission branch) is
   staged into the `git-repo-mirror` image and served read-only by `git daemon` behind a
   Service in `nagar-system`; `repoURL` = `git://git-repo-mirror.nagar-system.svc.cluster.local:
   9418/nagarvault.git`. Updating Argo's view = rebuild+push the mirror image with an immutable
   tag (`phase2-N`) and bump `newTag` — the same deliberate operator step as staging images.
   There is no receive-pack path into the mirror.
2. **On a production cluster this subtree is deleted** and `sourceRepos`/`repoURL` point at the
   authenticated internal git remote; no Application/Project semantics change.
3. **Kustomize build options live in `argocd-cm`** (`kustomize.buildOptions:
   "--load-restrictor LoadRestrictionsNone"`) to support the ADR-002 cross-root `deploy/
   third_party/` references.
4. **Kyverno webhook defaults are declared in git** (`spec.emitWarning`, `spec.admission`,
   per-rule `skipBackgroundRequests`, `validate.allowExistingViolations`): the webhook
   server-side-defaults ClusterPolicy objects, and undeclared defaults read as permanent drift
   to Argo's differ.

**Consequences.** Argo's view of git is bounded by the mirror cycle (deliberate pushes, no live
wiretap of the working tree); the 7-day drift-clean parity evidence is unaffected (cluster state
still = the mirrored git state). The `argocd-cm` key is version-sensitive and must be re-verified
on every Argo upgrade. Mirror images inherit the digest-pin discipline (I-5) via immutable tags.

---

## ADR-013 — Rebuild-from-scratch execution; k3d local substrate; no Compose restoration
**Status:** Accepted · **Date:** 2026-09-29 · **Phases:** 0 (baseline), 7 (app tier), 10 (cutover)

**Context.** The Day 0 audit found every service directory deleted from the working tree while
still present in git HEAD, and a legacy Compose stack of 15 healthy containers running on the
build host (untouched; ports 3000–4005 occupied). The repository owner directed: **no restoration
of the deleted files** — the application tier is re-implemented from scratch against the frozen
contracts (ARCHITECTURE §4.1–§4.3 endpoint/topic/storage registries, SECURITY §2–§3 JWT/RBAC/PII
chain, CONVENTIONS §4 port registry and §8 code conventions). No cluster existed; a disposable
local k3d cluster for the whole mission was approved (MISSION.md §3 authorizes exactly this).

**Decisions.**
1. **No Compose restoration.** The deleted `docker-compose.yml` / `docker-compose.dev.yml` stay
   deleted. ADR-004's freeze rationale ("Compose is the only runnable path") is superseded: from
   Phase 1 onward the Kubernetes path is the only path. Phase 10's deletion step becomes
   verification that no Compose remnants exist in the tree.
2. **App rebuild under contract conformance.** All nine components (authService, adminService,
   ingestion backend, frontend, vault-ui, queryService, slmService, schemaIndexer, enrichWorker)
   are re-implemented fresh; endpoint paths, topic names, bucket names, ports, JWT claims, the
   RBAC matrix and the PII denylist are copied verbatim from the registries. Behavioral drift is
   a bug.
3. **New per-service Dockerfiles are retained after Phase 10.** They are the build recipes a
   fresh operator needs to stage images into the internal registry; the legacy frozen
   Dockerfiles stay deleted. ADR-004's "delete all Dockerfiles" consequence is narrowed so.
4. **Local substrate = k3d with a paired local registry.** A per-cluster kustomize component
   rewrites the image prefix `registry.nagar.internal:5000` → the k3d registry while base
   manifests stay portable (ADR-001 portability contract intact). Digest pins are recorded as
   built; cosign signing keys are generated locally (offline mode — keyless signing is
   impossible in an air gap).
5. **The host Compose stack is never mutated by the mission.** It serves as the behavioral
   reference for parity gates. Stopping it (never deleting) is permitted only under memory
   pressure, with the owner's explicit approval in the moment.

**Consequences.** The legacy stack's images prove nothing about the rebuild; every Phase 7 gate
must be evidenced from the rebuilt services running in-cluster. The rebuild inherits a
greenfield expectation: tests accompany each service (the ingestion service keeps `npm test` /
`npm run check` per MISSION.md §3). The 7-day drift-clean parity item is evidenced over the
remaining mission window or honestly marked partial in the handover report.
