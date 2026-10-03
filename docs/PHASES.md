# Phases — NagarVault Implementation Plan

> The build order. Each phase is **isolated**: its own directory, charter, entry/exit criteria,
> rollback, and skip-consequence. Hub: [AGENTS.md](../AGENTS.md). Layout rules: [CONVENTIONS.md](CONVENTIONS.md) §1.

## 0. Isolation contract (applies to every phase)

1. **Subtree ownership.** Phase NN owns `deploy/phases/NN-*/` and nothing else. Cross-phase edits
   are forbidden (I-9). App code changes happen only in Phase 7 micro-phases, one service each.
2. **Independent reviewability.** Each phase merges as one self-contained PR set; the cluster stays
   healthy (or unaffected) with any subset of phases applied.
3. **Rollback.** `git revert` the phase's merge commits → Argo sync. Ownership labels
   (`nagar.io/phase`) make the blast radius greppable. Data-plane deletions never take PVCs with
   them (documented per phase below).
4. **Skip rule.** A phase may be skipped iff its "skip-consequence" is "none beyond lost capability."
   Phases 1, 7a, and 10 have mandatory-status; see their entries.
5. **Status ledger.** The table below is the single source of truth for phase status. Update it in
   the same PR that changes the phase.
   > **Rebuild deviation (2026-09-29, ADR-013):** Phase 7 re-implements every service from
   > scratch against the frozen registries; Phase 10 verifies the absence of Compose remnants
   > instead of deleting them, and retains the NEW per-service Dockerfiles as build recipes.

## 1. Phase status ledger

| # | Phase | Status | Charter (one line) | Skip-consequence |
|---|---|---|---|---|
| 0 | Documentation suite | **Done (2026-09-29)** — suite delivered in the Day-0 baseline commit `21472138` (mission log §0.3; no G0.x gate, which covers cluster bring-up) | This suite | impossible (foundation) |
| 1 | Cluster substrate | **Done (2026-09-29, k3d substrate)** — G1.1–G1.3 in the mission log | k3s + namespaces + cert-manager + Sealed Secrets + Kyverno/PSS | **mandatory** (all K8s phases need it) |
| 2 | GitOps control plane | **Done (2026-09-29, k3d substrate)** — G2.1–G2.2 in the mission log | Argo CD app-of-apps + `deploy/` skeleton | self-heal/prune lost; manual `kustomize apply` fallback documented |
| 3 | Object store & cache | **Done (2026-09-29, k3d substrate)** — G3.1–G3.4 in the mission log | MinIO + Redis + bucket Job | ingestion/backend phases (7) can't deploy |
| 4 | Messaging | **Done (2026-09-29, k3d substrate)** — G4.1–G4.6 in the mission log | Strimzi Kafka + topics + DLQ | ingestion + enrichWorker can't deploy |
| 5 | Relational store | **Done (2026-09-29, k3d substrate)** — G5.1–G5.6 in the mission log | CNPG 1.30.1 + migration Job + backups + restore drill | auth/query/admin/enrich can't deploy |
| 6 | Vector & LLM tier | **Done (2026-09-29, k3d substrate)** — G6.1–G6.6 in the mission log | Qdrant + Ollama + model Job + schemaIndexer | slm + RAG features can't deploy |
| 7a–7g | App tier (per service) | **7a Done (2026-09-30, k3d); 7b Done (2026-09-30, k3d); 7c Done (2026-09-30, k3d); 7d Done (2026-09-30, k3d); 7e Done (2026-09-30, k3d); 7f Done (2026-09-30, k3d); 7g Done (2026-09-30, k3d)** — gates G7a.1–G7a.7, G7b.1–G7b.7, G7c.1–G7c.5, G7d.1–G7d.7, G7e.1–G7e.5, G7f.1–G7f.5, G7g.1–G7g.3 in the mission log (§2 Phase 7 below lists them per micro) | Deploy each of the 7 app components in dependency order | per-service; UI phases depend on 7a–7d |
| 8 | Edge & TLS | **Done (2026-09-30, k3d substrate)** — G8.1–G8.7 in the mission log | Traefik routes, cert-manager certs, CORS + rate-limit middleware | platform reachable only via port-forward workarounds |
| 9 | Observability & hardening | **Done (2026-10-03, k3d substrate)** — G9.0–G9.8 in the mission log | Prometheus + Loki + full Kyverno set + NetworkPolicy completion | blind ops; policy gaps — strongly discouraged |
| 10 | Parity cutover & cleanup | **Complete (2026-10-03, k3d substrate)** — G10.0–G10.7 in the mission log | E2E parity gate → delete Compose & Dockerfiles → README rewrite | **mandatory** (the cutover is what certifies the shipped state) |

## 2. Phase charters

### Phase 1 — Cluster substrate
- **Files:** `deploy/phases/01-substrate/` (namespaces, SealedSecrets `nagar-jwt` etc., Kyverno
  baseline policies, cert-manager manifests, PSS labels).
- **Entry:** hardware/registry per OPERATIONS §1. **Exit:** `kubectl get ns` shows the five
  namespaces; Kyverno reports the baseline policies active; a sealed secret round-trips.
- **Rollback:** delete namespaces (nothing else exists yet). **Notes:** k3s install itself is
  documented in OPERATIONS §2 (host-level, outside git except a bootstrap script).

### Phase 2 — GitOps control plane
- **Files:** `deploy/phases/02-gitops/` (argocd manifests, app-of-apps, `deploy/third_party/` for
  vendored operator charts per ADR-002).
- **Exit:** app-of-apps shows child Applications; a test change propagates via git push only;
  self-heal reverts a manual mutation within ~1 sync period (this is the zero-maintenance proof).
- **Rollback:** delete Argo Applications (workloads keep running); revert to `kustomize apply` mode
  (documented degraded mode).

### Phase 3 — Object store & cache
- **Files:** `deploy/phases/03-object-cache/` — MinIO & Redis StatefulSets (exemplars:
  `minio-statefulset.yaml`, `redis-statefulset.yaml`), bucket init Job, NetworkPolicies.
- **Exit:** buckets `raw-media` + `raw-sensitive-media` exist; Redis passes ping; PVCs bound.
- **Rollback:** scale to zero / delete manifests. **PVC safety:** deleting the StatefulSet does not
  delete PVCs (k8s semantics); phase docs restate this.

### Phase 4 — Messaging
- **Files:** `deploy/phases/04-messaging/` — Strimzi `Kafka` CR (KRaft single node, ADR-005/006),
  topics Job (`kafka-topics-job.yaml`), DLQ topic, NetworkPolicies.
- **Exit:** six topics exist with correct names (ARCHITECTURE §4.2); a test event round-trips.
- **Rollback:** delete Kafka resource; producers/consumers of phases not yet deployed are unaffected.

### Phase 5 — Relational store
- **Files:** `deploy/phases/05-postgres/` — CNPG `Cluster` (2 replicas, ADR-006), migration Job
  (`postgres-migration-job.yaml`), scheduled backups to MinIO `pg-backups` bucket, restore test.
- **Exit:** `001_create_tables.sql` applied; `SELECT 1` via `postgres-rw`; a backup completed; a
  restore drill into a scratch cluster succeeded.
- **Rollback:** CNPG finalizers documented — deleting the Cluster CR does not delete PVCs; use
  cnpg tooling if a real teardown is intended.
- **Implementation notes (2026-09-29, ADR-019/ADR-020):** the warehouse schema's canonical home is
  `deploy/phases/05-postgres/migrations/001_create_tables.sql`. ARCHITECTURE §3.3 previously named
  `enrichWorker/migrations/`, a path that no longer exists after the service tree was removed
  (ADR-013) — the phase that owns the relational store authors and delivers its schema, and Phase
  7c's enrichWorker consumes that same DDL rather than forking a copy. Backups use CloudNativePG's
  native `barmanObjectStore` integration (deprecated upstream since 1.26 but functional in 1.30,
  with a named migration trigger to the Barman Cloud plugin). The restore drill is a buildable
  subtree that Argo deliberately does not reconcile (`deploy/phases/05-postgres/restore-drill/`),
  applied by an operator per OPERATIONS §7 — the exit criterion is evidenced by a verify Job that
  connects as the application role, not by a pod being up.

### Phase 6 — Vector & LLM tier
- **Files:** `deploy/phases/06-vector-llm/` — Qdrant + Ollama StatefulSets, model Job
  (`ollama-model-job.yaml`, ADR-010), schemaIndexer Job + Deployment, NetworkPolicies.
- **Exit:** `ollama list` shows both models; Qdrant `nagar_schema` holds 40 vectors; `/reindex`
  idempotent re-run works.
- **Implementation notes (2026-09-29, ADR-021):** models are staged into a shared RWX PVC by the
  checksum-verified Job (`MODEL-JOB-OK`) instead of a StatefulSet volumeClaimTemplate, so the Job
  can populate the volume before ollama-0 ever starts. Two upstream-behavior fixes are documented
  in manifest comments: qdrant 1.15.1 ignores the storage-dir env override (fixed via
  `workingDir: /qdrant` + a `snapshots` emptyDir — under `readOnlyRootFilesystem` the actix init
  panics on `./snapshots/tmp` otherwise), and qdrant point ids must be **unsigned** integers
  (indexer folds doc-id sha256 prefixes as u64). Evidence: G6.1–G6.6 in the mission log.

### Phase 7 — App tier (one service per micro-phase, isolated rollbacks)
Order follows ARCHITECTURE §4.4 dependency graph; each micro-phase is its own PR with its own
rollback:

| Micro | Service | Deps | Exit criterion |
|---|---|---|---|
| 7a | authService | PG | seeded admin; `/login` E2E via cluster-internal curl (**exemplar parity check** vs `auth-service-deployment.yaml`) — **Done 2026-09-30** (fresh rebuild in `deploy/phases/07-app-auth/`, G7a.1–G7a.7 in the mission log; 17/17 E2E checks, parity 11/11) |
| 7b | queryService | PG, auth | `/query` executes + RBAC blocks correctly; audit row written — **Done 2026-09-30** (fresh rebuild in `deploy/phases/07-app-query/`, G7b.1–G7b.7 in the mission log; 13/13 gate matrix, 11/11 audit rows, cross-service jti denylist) |
| 7c | enrichWorker | Kafka, PG | events flow topic→table; DLQ on malformed input — **Done 2026-09-30** (fresh rebuild in `deploy/phases/07-app-worker/`, G7c.1–G7c.5 in the mission log; live topic→table upsert with duplicate-refresh, DLQ-INSPECT-OK, wire envelope documented for 7e) |
| 7d | slmService | Ollama, Qdrant, query | `/ask` returns SQL + rows — **Done 2026-09-30** (fresh rebuild in `deploy/phases/07-app-slm/`, G7d.1–G7d.7 in the mission log; E2E-SLM-OK with caller-token RBAC inheritance, admin 403 pass-through proven; exposed and fixed the COUNT(*) gate over-block and the indexer's async count-witness race) |
| 7e | ingestion backend | MinIO, Redis, Kafka, auth | presign→PUT→event→Kafka E2E — **Done 2026-09-30** (fresh rebuild in `deploy/phases/07-app-ingestion/`, G7e.1–G7e.5 in the mission log; full API E2E 202-commit + 200-duplicate + 400 malformed-gates + 200 media PUT, row enriched into `nmc_complaints` by the 7c worker; fixed the service-env NaN-port crash and the minioOk health-path, re-sealed the drifted `nagar-minio` consumer secret) |
| 7f | adminService | PG, Kafka, schemaIndexer | `/health/cluster` all-up; `/dlq`, `/audit-logs` live — **Done 2026-09-30** (fresh rebuild in `deploy/phases/07-app-admin/`, G7f.1–G7f.5 in the mission log; E2E: all-up health summary, DLQ tail incl. a live malformed→worker→DLQ round-trip, real audit rows, officer 403 + no-auth 401 matrix; `/vector/resync` deferred to 7g per ADR-022) |
| 7g | frontend + vault-ui | 7a–7f endpoints | browser E2E: login, dashboard, ask — **Done 2026-09-30** (fresh rebuild in `deploy/phases/07-app-ui/`, G7g.1–G7g.3 in the mission log; E2E through the BFF: real logins + httponly cookie relay, officer ask with RBAC-inherited rows, admin 403 `table-rbac` pass-through, health-officer query allowed, PII probe 403 `pii-column`, no-cookie 401 + bad-creds 401; injector round-trip 202 → row in `nmc_complaints`; second qdrant segment-corruption panic recovered via `/reindex` — §12.33; BFF architecture per ADR-023) |

### Phase 8 — Edge & TLS
- **Files:** `deploy/phases/08-edge/` — Traefik IngressRoutes (port map: `/`→frontend, `/api`→
  ingestion, `/auth`→auth, `/admin`→admin; plus `/minio`→minio for presigned PUTs), cert-manager
  internal-CA `Certificate`s, CORS middleware (replaces per-bucket MinIO CORS), rate-limit
  middleware (defense-in-depth).
- **Exit:** OPERATIONS §11 smoke steps 1–2 pass over HTTPS; browser presigned PUT works from the
  frontend origin.
- **Rollback:** edge-only; in-cluster paths unaffected.
- **Done 2026-09-30 (k3d substrate, ADR-024):** all routes live — 15/15 Applications
  Synced/Healthy; OPERATIONS §11 smoke steps 1–2 green over HTTPS (`SMOKE-1-OK`; login 200 with a
  `Secure` cookie; invocation note added to §11 — host-side `-k` + port-forward per §12.34).
  Six E2E gates green (G8.1–G8.7 in the mission log): TLS chain to `CN=nagar-edge-ca` (the
  ≥TLS-1.2 floor is declared by the deployed TLSOption in both route namespaces; the host
  toolchain cannot offer ≤1.1, so the negative probe is instrument-limited — corrected in
  G8R.1), CORS preflight allow/deny matrix, rate-limit burst with both 429 shapes attributed
  (edge Retry-After vs auth in-app), presigned PUT through the edge byte-intact into MinIO,
  401/403 authz matrix with admin contrast, in-cluster verbatim `/api` + native-path flows
  unaffected. Charter deviation **closed 2026-10-01**: the literal *browser*-origin presigned PUT
  was originally blocked by 7e's presigner (`MINIO_URL` only, so minted URLs carried
  cluster-internal DNS). 7e image `phase7e-4` now mints the URL on the public edge origin under
  the frozen `/minio` route (`PRESIGN_PUBLIC_URL`; ADR-025), and Gate 4 was re-run literally from
  the host — API presign → PUT through the edge → bytes verified in MinIO (mission log, G8C). Traefik
  v3 field rules live-proven and encoded in ADR-024: per-namespace middlewares/TLSOptions,
  parenthesized host disjunctions, vendored 10-CRD bundle + RBAC incl. endpointslices/nodes,
  dedicated plaintext ping entrypoint, strip map for native-path upstreams (§6 correction).

### Phase 9 — Observability & hardening
- **Files:** `deploy/phases/09-observability/` + NetworkPolicy completion + full Kyverno set
  (SECURITY §5/§8) + alert rules with runbook anchors (OPERATIONS §10).
- **Exit:** dashboards populated; one alert intentionally fired and linked to its runbook; restore
  drill evidence recorded.
- **Done 2026-10-03 (k3d substrate):** the observability half verified end to end through the
  deployed surface, not by manifest review (G9.0–G9.8 in the mission log): an authenticated Grafana
  console showing both provisioned datasources; the Phase-8 edge serving the console (200) and the
  ingestion app (200 `{api,minio,kafka}` in-cluster, 401 at its `/api` boundary); live metric+log
  telemetry from a single edge request (Traefik counter + the matching access-log line in Loki);
  10/10 scrape targets up; and one intentional `PodCrashLooping` fired **and delivered to
  Alertmanager** carrying `runbook_url: docs/OPERATIONS.md#rb-12.1`. Delivery was a first-sync defect
  (Prometheus had no `alerting:` block, so the rule fired and stopped there) fixed in `53a0f1fa`
  through the normal git→mirror→Argo cycle.
- **Done 2026-10-03 — Kyverno admission gate (G9.8):** all three probes from
  `e2e/fixtures/policy-violation-pods.yaml` were **denied** (`require-image-digest` on the `:day0`
  tag; `restrict-image-registries` on the `docker.io` host; host-namespace access) and the compliant
  control ran to `Completed` printing `p9 control: admitted`, so the policies do not over-block.
  Recorded precedence nuance: every mission namespace is `pod-security.kubernetes.io/enforce=
  restricted`, and the in-tree PodSecurity plugin runs before validating webhooks, so the
  `hostNetwork` probe is rejected by PodSecurity and Kyverno's `disallow-host-access` is not the
  decision inside those namespaces — that policy (Enforce, all namespaces but kube-system*) was
  proven separately with a `--dry-run=server` probe in an unlabeled namespace, plus a compliant
  negative control, with nothing persisted. The reporting path of SECURITY §8 is live:
  PolicyReports carry 1061 results (1027 pass / 34 fail, all from the Phase-1 baseline policies
  against Kyverno's own workloads — out of this phase's scope) and the reports-controller
  `/metrics` answers HTTP 200 with 1209 Kyverno series. There is deliberately no Prometheus alert
  on policy violations: Kyverno is not one of ADR-026 §1's scrape jobs, and ADR-026 §3 defers the
  `policy-reporter` UI, so PolicyReports + `/metrics` are the documented surface.
- **Restore-drill criterion:** already met by the Phase-5 drill (G5.5, `RESTORE-DRILL-VERIFIED`);
  no new drill was required for this phase.

### Phase 10 — Parity cutover & cleanup (Complete)
- **Entry:** OPERATIONS §11 smoke script green on K8s; parity checklist below signed.
- **Actions:** delete `docker-compose.yml`, `docker-compose.dev.yml`, all per-service `Dockerfile`s
  and `.dockerignore`s (ADR-004); audit stray tracked `.env` files (several per-service `.env`
  files exist today — review and remove); resolve the nested `frontend/frontend/Dockerfile`
  duplicate; rewrite README; flip PHASES.md ledger to "Complete."
- **Parity checklist:** all 6 topics consumed; all 5 dept tables written; RBAC matrix enforced;
  PII denylist enforced; DLQ inspectable; backups restore; smoke test green over HTTPS; Kyverno
  clean; no drift in Argo for 7 consecutive days.
- **Rebuild deviation (2026-09-29, ADR-013):** Compose files are already absent from the tree —
  this phase VERIFIES their absence instead of deleting them, keeps the NEW per-service
  Dockerfiles as operator build recipes, and includes the `docker-compose.yml` the legacy stack
  left inside `nagar-vault-backend/` in the audit scope.

## 3. Rollback doctrine (all phases)

1. `git revert` the phase merge(s) — never hand-edit live state (I-1).
2. Argo sync. Prune removes what git no longer declares.
3. PVCs and CNPG/Strimzi finalizers are the only dangerous edges; both are documented per phase
   (Phase 3/5/6) and deletion of data requires an explicit, reviewed, typed command — it is never a
   side effect of a rollback.
4. If a rollback itself fails: `argocd app history` + last-known-good git tag
   (`release/YYYY-MM-DD`), then escalate to a human. A degraded cluster that matches git is
   preferable to a "fixed" cluster that doesn't.

## 4. Verification gates (every phase)

- `kustomize build` clean (I-12); `kubectl --dry-run=client` clean on changed files.
- `nagar.io/phase` + `nagar.io/tier` labels present (CONVENTIONS §5).
- No plaintext secrets in the diff (I-3) — CI greps for `stringData:`/`data:` on Secret kinds.
- Docs updated in the same PR (AGENTS.md §6.2).
