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

---

## ADR-015 — MinIO and mc are source-built and staged locally (upstream registries unreachable)
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 3

**Context.** Phase 3 needs a MinIO server image and the `mc` client image. Every MinIO distribution
channel is unreachable from this network (verified 2026-09-28/29: `docker.io/minio/*` → pull access
denied, `quay.io/minio/*` → 401, `dl.min.io` / `mirror.gcr.io` / `public.ecr.aws` / bitnami → no
route). Reachable and sufficient: `docker.io/library/*`, `registry.k8s.io`, `quay.io/argoproj/*`,
`proxy.golang.org`, `raw.githubusercontent.com`. MinIO is written in Go, so the Go module proxy is
an adequate source channel. I-11 requires that every image be obtainable into the internal
registry; ADR-013 §4 already ratifies staging built images into it.

**Decisions.**
1. **Compile from upstream git tags, pinned by name:** server `RELEASE.2025-10-15T17-29-55Z` (the
tag the legacy Compose stack ran — parity reference), `mc` `RELEASE.2025-08-13T08-35-41Z`.
2. **Recipe**: `agentic/tmp/build-minio3.sh` — `golang:1.24-alpine`, `CGO_ENABLED=0`,
`GOPROXY=https://proxy.golang.org,direct`, `go build -trimpath -ldflags='-s -w'`. Output digests
recorded: server `36450819e0fa37907d2e8f225ef207f491e8f3a81cd3142e7f6370f0bb26e477`, mc
`e37fe3ed86cb4944d7d4bd0b1b8ac7fa3b74d54b5b5ce5acec870b8c2bef45bf`.
3. **Checksum gate at image build**: `images/minio.Dockerfile` / `images/minio-mc.Dockerfile` take
`ARG *_SHA256` and `sha256sum -c` the staged binary, so a mismatched compile output cannot be
packaged; both images run as uid 1000 on alpine (non-root, PSS `restricted`).
4. **Staged into the internal registry and consumed by digest** (I-5): `mission/minio@sha256:
d8464e6c…`, `mission/minio-mc@sha256:72e8defd…`, pushed via `localhost:35000` and pulled
in-cluster via `k3d-nagar.localhost:5000` (Day-0 G0.2 transport).
5. **This is a substrate workaround, not the production plan.** In the air-gapped production
enclave the vendor's images arrive with the import bundle; when such a path exists these two
Dockerfiles are deleted and upstream digests are pinned instead.

**Consequences.** Upstream's image-level CVE pipeline no longer covers these two artifacts —
MinIO CVE tracking is now ours. The SECURITY §7 supply-chain steps (`syft` SBOM → `trivy` gate →
`cosign sign`) are **not yet produced** for them; recorded as open gap R8 (SECURITY §7 itself marks
that CI as not-yet-built). Rebuilds require the Go proxy, which is available on the connected build
host and never needed in-cluster.

---

## ADR-016 — Convergence on purpose-built workloads: declared server defaults and declarative Job replacement
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 3

**Context.** Two divergence traps hit Phase 3, both ending in the same wedged state:

- **(a) Immutable Job template.** The `bucket-init` Job's pod spec changed (an `mc` env-var fix). A
  Job pod template is immutable, so Argo cannot land the change: a dry run against the live Job
  returns `spec.template: Invalid value: … field is immutable`. The sync fails and Argo then
  refuses to retry that revision — `Skipping auto-sync: already attempted sync to [<rev>] with
  timeout 0s (retrying in 53.6s)` — so the fix sat in git while the live Job kept failing.
- **(b) Un-normalized server defaults.** The `minio` StatefulSet was `OutOfSync` after *every*
  sync: the API server defaults `apiVersion`, `kind` and `spec.volumeMode` inside
  `spec.volumeClaimTemplates`, and Argo's client-side differ does not normalize that subtree. The
  damage was not cosmetic: because the app never converged, Argo's self-heal issued **partial**
  syncs (`Resources:[]SyncOperationResource{{Kind:StatefulSet,Name:minio}}`), and each partial sync
  marked the revision "already attempted" — starving the full auto-sync that would have carried the
  Job fix. The redis StatefulSet has no `volumeClaimTemplates` and stayed `Synced` with the same
  class of pod-spec defaults omitted, which localized the drift.

**Decisions.**
1. **Job replacement is declared in git**, not commanded by hand:
   `argocd.argoproj.io/sync-options: Force=true,Replace=true` on the Job (upstream's documented
   option for Jobs whose spec changes). Observed across two cycles: the Job is deleted and
   recreated **exactly when its desired spec changes**, and is not re-run on syncs where the spec
   is unchanged — so the idempotent bucket Job does not churn (I-2).
2. **Server-side defaults are declared in git** for `volumeClaimTemplates` — the Phase-2 precedent
   for the Kyverno webhook defaults (declare, never mask). `ignoreDifferences` is rejected: it
   would hide real drift in a storage spec.
3. **Diagnosis method is now part of the method:** exhaustive desired-vs-live comparison, plus a
   read-only `kubectl diff --server-side [--force-conflicts]`. A resource that is clean under
   server-side semantics but drifts under Argo's client-side differ points directly at a subtree
   Argo does not normalize.
4. **Server-side diff is deferred, not rejected.** The pinned v3.5.3 controller binary contains the
   `ServerSideDiff` sync option and `--server-side-diff` / `--server-side-diff-enabled` /
   `--server-side-diff-concurrency` flags, but adopting them changes the Argo control plane
   (Phase-2 subtree) and must be verified first. Until then, convention 2 stands for every
   StatefulSet that uses PVC templates.

**Consequences.** Every future `volumeClaimTemplates` block carries the three declared defaults
(a convention, not an accident); every Job whose spec may change must carry the sync-options
annotation or a spec edit silently wedges the app; and the failure mode *OutOfSync forever →
self-heal partial syncs → auto-sync starvation* is documented with its diagnostic
(OPERATIONS §12.13–12.14).

---

## ADR-017 — Strimzi 1.2.0 as the messaging substrate: API shape, label ownership, and API access
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 4

**Context.** Phase 4 could only reach Strimzi **1.2.0** from this network. That version is a
generational break from the shape the Phase-0 exemplar (`docs/manifests/exemplars/
kafka-strimzi.yaml`) and ADR-005/006 were written against, and three separate facts about it
each cost a failed deploy to find. All three are upstream-documented but counter-intuitive, and
all three are invisible to `kustomize build` and `kubectl apply --dry-run=server` — they only
appear once the Cluster Operator reconciles on a live cluster.

1. **The node pool is a separate, mandatory object.** Since Strimzi 0.42 the node count, storage,
   resources and JVM options live on a `KafkaNodePool` CR, the API version is `kafka.strimzi.io/v1`
   (`v1beta2` is gone), and a Kafka CR alone has **zero** nodes.
2. **Pods carry the operator's labels, not ours.** Upstream: "These labels cannot be overridden
   through template configuration of Strimzi resources." Measured on the real pod, the operator
   rewrites `app.kubernetes.io/part-of` to `strimzi-nagar`, `managed-by` to
   `strimzi-cluster-operator`, `instance` to `nagar`, sets `name` to `kafka`, and **drops**
   `app.kubernetes.io/component` entirely.
3. **Brokers need the Kubernetes API.** Strimzi 1.x loads the cluster CA / trust bundle through
   Kafka's `KubernetesSecretConfigProvider` instead of volume mounts, so a broker pod reads Secret
   `nagar-trustbundle` over the API server *before it can start*.

**Decisions.**
1. **The messaging tier follows 1.2.0's actual contract, and the exemplar is treated as a shape
   reference, not a spec.** `Kafka` + `KafkaNodePool` (dual-role single node, ADR-006 unchanged),
   `apiVersion: kafka.strimzi.io/v1`, storage/roles/resources/JVM on the pool. The head of
   `deploy/phases/04-messaging/kafka.yaml` carries the deviation list so the next reader does not
   rediscover it. **ADR-005 and ADR-006 are unchanged in substance**: the operator still owns the
   Kafka lifecycle and the single-node risk acceptance stands. The Entity Operator stays
   undeployed (documented reason: it buys nothing this phase consumes and costs two JVMs against
   the binding memory constraint, risk R1).
2. **A node pool is adopted by a label + an annotation, and both are declared in git.** The Kafka
   CR carries `strimzi.io/node-pools: enabled`; the pool carries `strimzi.io/cluster: <kafka-name>`
   (upstream: the label "must be set to the name of the Kafka custom resource"). Missing either
   half yields `InvalidConfigurationException: No KafkaNodePools found for Kafka cluster nagar`
   and **no pods at all** — the operator refuses the entire CR, so the symptom is a `Degraded`
   Application over an empty `Kafka` status, not an obvious error.
3. **Pod selectors bind to Strimzi's label set, and git does not declare labels the operator will
   discard.** Every NodePolicy/Service selector in this phase targets `strimzi.io/cluster` /
   `strimzi.io/kind` / `strimzi.io/name` / `strimzi.io/broker-role` — the same selector Strimzi
   puts on its own `<cluster>-kafka-bootstrap` and `<cluster>-kafka-brokers` Services. The pod
   templates declare only the labels the operator does not reserve (`nagar.io/phase`,
   `nagar.io/tier`). This is a correctness rule, not tidiness: a selector on
   `app.kubernetes.io/component: broker` matches **no pod at all** and fails silently — a Service
   with no endpoints and a NetworkPolicy with no subject, both of which look healthy in git.
4. **`require-nagar-labels` gets one scoped operator carve-out, and only for `part-of`.** The
   `check-part-of-label` rule excludes pods labeled `app.kubernetes.io/managed-by:
   strimzi-cluster-operator`. Alternatives were worse: relaxing the pattern for every pod would
   weaken the rule globally, and the label genuinely is not ours to set. `check-phase-label` still
   applies in full to those pods, so the operational purpose of the schema — enumerate every pod
   by mission phase — survives intact. This is a Phase-1 file amended by a Phase-4 finding, the
   same way ADR-015/016 amended the docs suite; the carve-out is in git and scoped by the
   operator's own self-declared label.
5. **Broker API access is granted by an explicit, port-scoped egress NetworkPolicy** the phase
   owns (`allow-kafka-api-egress`), rather than by re-enabling Strimzi's runtime policy
   generation — which would put objects in the cluster that git does not declare (I-1) and add an
   allow-from-anywhere listener rule that widens SECURITY §8's default-deny. The rule allows
   exactly the two API ports (443 ClusterIP form, 6443 post-DNAT) and relies on the air gap plus
   `default-deny` for every other port; the rationale for not naming the API server by `ipBlock`
   is recorded in the manifest.
6. **A server-pruned schema node is declared, not masked.** The vendored Kafka CRD ships an empty
   `…/status/properties/clusterSecurity/properties: {}`, and the API server prunes empty
   `properties` nodes from a structural CRD schema on write. The live object therefore never
   contains the key and Argo — which cannot distinguish "the server dropped this" from "a human
   changed this" — reported that one CRD `OutOfSync` after every sync, forever, while the other
   eleven CRDs from the same file converged. Per ADR-016's rule, the fix declares the stored form:
   a JSON 6902 patch in this phase removes the empty node from the vendored document, so
   `deploy/third_party/` stays pristine (ADR-002). `ignoreDifferences` was rejected: on a CRD it
   would hide genuine schema drift, and the Kafka schema is the one most likely to move under a
   Strimzi upgrade. The method that found it is worth reusing — `argocd app diff` rendered the
   entire discrepancy as a single line (`> properties: {}`), which is the signature of server
   normalization rather than drift.
7. **Every listener the operator actually runs gets an ingress rule, scoped to its real users.**
   The tier's NetworkPolicy was originally written for the one documented client port. Strimzi 1.x
   also runs `REPLICATION-9091` — which is what the Cluster Operator's AdminClient uses — and
   `CONTROLPLANE-9090` for the KRaft quorum. The result was a broker that started, served clients
   and ran the topics Job perfectly while every operator reconciliation stalled on `Error getting
   broker config: TimeoutException`, i.e. the platform worked and the control plane did not.
   Ingress is now one rule per listener: 29092 from in-namespace + `nagar-app`, 9091 from
   in-namespace + `nagar-system`, 9090 from broker pods only. The ports were confirmed by probing
   them from the operator pod rather than read off a diagram.
8. **A failed pod-create is not retried by the pod-set controller.** When Kyverno denied the broker
   Pod, `StrimziPodSet/nagar-dual-role` recorded the error and then did nothing further: the
   controller reconciles on StrimziPodSet change events, and the desired pod-set content was
   unchanged, so there was no event to react to. The un-wedge is to delete the StrimziPodSet (the
   operator regenerates it from the Kafka CR in git, which is what it did on the next periodic
   reconciliation). Documented in OPERATIONS §12.15 because the symptom — "operator waits 300 s
   for a pod that does not exist" — points at the wrong layer.

**Consequences.** Phase 4's shape is pinned to 1.2.0's contract; a later Strimzi upgrade is a
deliberate change to `deploy/third_party/strimzi/` plus this ADR's review, not a drift. Any future
Strimzi-managed tier (Connect, MirrorMaker, Cruise Control) inherits decisions 3–5 verbatim: use
the operator's selectors, assume it owns `app.kubernetes.io/*` on its pods, and expect its pods to
need API access. The `component: broker` selector is now a documented trap; Phase 9's policy work
should consider an `ipBlock`-based replacement for `allow-kafka-api-egress` when the real
deployment's control-plane range is known.

---

## ADR-018 — Advancing the git transport is an out-of-band operator step, not a cluster mutation
**Status:** Accepted · **Date:** 2026-09-29 · **Phases:** 2 (mechanism), 4 (first documented use)

**Context.** ADR-014 made Argo CD read desired state from an in-cluster git mirror image, with a
mirror cycle = "rebuild+push the mirror image with an immutable tag and bump `newTag`". Phase 4
exposed that this description is incomplete, because it is circular: Argo learns the new tag
**from the mirror pod**, and the mirror pod is itself an Argo-managed Deployment. A pod running
tag `phaseN-x` serves a tree that declares `phaseN-x`, so Argo reads it as `Synced` and never
learns that `phaseN-(x+1)` exists. Every phase so far advanced only because an out-of-band step
was performed, and I-1 read narrowly would make that step illegal → the mission would deadlock on
its own GitOps rule.

**Decisions.**
1. **The mirror advance is declared a sanctioned transport step**, in the same class as staging an
   image into the registry or pushing to a production git remote (ADR-014): the operator applies
   the mirror subtree once per cycle with
   `kustomize build deploy/phases/02-gitops/git-mirror | kubectl apply --server-side --force-conflicts -f -`.
   Applying the *same git tree Argo reads* keeps the strongest available form of I-1 — the live
   object is byte-identical to the declared one, so there is nothing to self-heal back. It is
   recorded as exception 4 in OPERATIONS §9.
2. **The cycle order is content → tag bump → payload → push → transport apply.** The payload is
   cloned *after* the commit that declares its own tag, so the served tree and the running pod
   agree; and it carries **both** the content change and the bump, which is why one cycle lands
   both. Getting this order wrong is a hard deadlock (proved: the first `phase4-2` build served a
   tree declaring `phase4-1`, so Argo would have self-healed the transport backwards to a mirror
   that never contained the fix).
3. **A mirror tag is never re-pushed under the same name.** `phase4-2` was pushed from a
   pre-bump commit and abandoned unread; the corrected cycle used a fresh `phase4-3`. This is the
   node image cache lesson from Phase 2 (G0.3 note 3 / the `:phase2` tag-reuse trap) applied
   deliberately rather than rediscovered.

**Consequences.** Cluster state remains equal to the mirrored git state at all times, and the
one step that cannot be expressed as "change git, let Argo converge" is now written down with its
exact command instead of being improvised per phase. The honest residual gap is that a fresh
operator must perform this step by hand: the structural fix — moving `git-mirror` out of the
Argo-managed tree so that updating the transport is ordinary bootstrap (like the k3s install in
OPERATIONS §2) rather than an exception to I-1 — is recorded here as the recommended Phase-9/10
cleanup, not silently deferred. Until it lands, this ADR is the authority for the step.
