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

---

## ADR-019 — CloudNativePG 1.30.1 as the relational substrate: native Barman backups, pinned app credentials, and three exemplar fields that do not exist
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 5

**Context.** Phase 5 delivers the warehouse PostgreSQL (ADR-005/006: CloudNativePG, 2 instances,
WAL + base backups into the `pg-backups` bucket Phase 3 created). Three facts forced choices the
Phase-0 exemplar could not have known. (a) CloudNativePG's current stable line is **1.30**, and
native Barman Cloud support has been **deprecated since 1.26** in favour of the Barman Cloud
plugin. (b) The exemplar predates any live run and contains fields that the 1.30 CRD does not
define. (c) The service tree was deleted before the mission began (ADR-013), so the warehouse
schema the migration applies had to be authored rather than copied from application code.

**Decisions.**
1. **Operator 1.30.1; PostgreSQL 15.** 1.30.1 is the newest stable release (published
   2026-09-23) and is vendored as a static manifest per ADR-002. The *major* version is not a
   preference: the exemplar documents the "postgres:15 line", and the frozen legacy stack's
   `docker-compose.yml` pinned `postgres:15-alpine` — recovered from git history at `21472138~1`,
   which is the behavioural reference ADR-013 mandates rebuilding against. The operand is
   therefore the 15.17 line of the CloudNativePG image, chosen because it ships the
   `barman-cli-cloud` tooling the native backup path invokes.
2. **Native `barmanObjectStore` backups now, with an explicit migration trigger to the plugin.**
   The deprecated-in-tree integration is what the exemplar, ARCHITECTURE §4.3 and OPERATIONS §7
   all describe, and it keeps the air-gap surface minimal: the plugin would add a second operator
   Deployment, its own CRD, cert-manager-issued serving certificates and a randomly-named Secret
   inside its manifest, at version 0.15.0 (pre-1.0). The accepted risk is written down rather than
   assumed: upstream says the native integration "remains functional" but "will be removed in a
   future release", so **the migration trigger is the 1.31 upgrade or the first upstream
   deprecation warning** — whichever comes first — and the documented path is upstream's
   "Migrating from Built-in CloudNativePG Backup". One operational consequence is inherited from
   Barman Cloud 3.16+: the toolchain no longer creates the target bucket, so Phase 3's `pg-backups`
   bucket is a hard prerequisite of this phase, not a convenience.
3. **The controller stays in its upstream-native `cnpg-system` namespace**, the same posture
   Phase 1 took for the cert-manager and kyverno bundles — and explicitly *not* the relocation
   Phase 4 performed on Strimzi. The bundle hardcodes `cnpg-system` in 15 places (RBAC subjects,
   webhook `clientConfig`, leader election), it ships its own Namespace document, and the reason
   Strimzi had to move does not apply here: Strimzi was relocated because the data-plane namespace
   carries a namespace-wide `default-deny` that would have blinded its egress to the API server,
   whereas `cnpg-system` has no default-deny and therefore needs no policy hole. What relocating
   would buy (one operator namespace instead of two) does not pay for fifteen hand-patched
   references. The namespace is PSS-labelled by a patch in this phase so it is not the one
   ungoverned namespace in the cluster.
4. **`affinity.podAntiAffinityType: preferred`, overriding the exemplar's `required`.** On a
   single-node cluster, `required` makes the second instance permanently unschedulable: the
   anti-affinity term matches its own cluster's pods on the same `kubernetes.io/hostname`.
   Upstream documents `preferred` as the default and warns that `required` "may cause pods to
   remain pending". Two instances on one node is the honest shape of this substrate; `required` is
   the right production posture and is a one-word change when a second node exists.
5. **The application role's password is pinned, not generated.** CloudNativePG's
   `bootstrap.initdb.secret` takes a `kubernetes.io/basic-auth` secret whose username must equal
   `initdb.owner` and whose password becomes that role's password. Phase 1 already sealed the
   `nagar` password into the app tier's `nagar-app/nagar-postgres-app.databaseUrl`, so letting the
   operator generate a fresh one would split SECURITY §6.2's key map into two disagreeing halves —
   and repairing that later would mean re-sealing another phase's secret (I-9). Instead this phase
   seals its own namespace-local copy, `nagar-postgres-bootstrap`, carrying **the password already
   in the cluster**: read from the live unsealed Secret, never printed or committed in the clear,
   re-sealed offline against the controller certificate, plaintext shredded. Consequence for
   SECURITY §6.4: rotating the database password now means re-sealing that blob *and* the app
   tier's `databaseUrl` in the same change.
6. **The migration Job connects as the operator-managed superuser.** The migration creates the two
officer roles and reassigns object ownership, so it needs superuser or `CREATEROLE` rights; the
   `nagar` role is deliberately neither. Granting it `CREATEROLE` for the platform's lifetime to
   match the exemplar's credential choice would widen the application role permanently to save a
   one-second connection, so the Job consumes the operator-generated `postgres-superuser` secret
   instead — which also means no database credential is ever committed (I-3).
7. **Warehouse objects are owned by `nagar`, and the officer roles hold SELECT only**
   (`nmc_officer` without health records, `health_officer` with them, neither able to touch
   `users`/`sessions`/`audit_logs`) — SECURITY §3.3's "second wall", implemented as grants rather
   than promised. `nagar` is made a member of both officer roles so queryService can activate the
   wall with `SET ROLE` in Phase 7b. The JWT constant `ROLE_HEALTH_OFFICER` maps to the PostgreSQL
   role `health_officer`, because PostgreSQL folds unquoted identifiers to lower case.
8. **Three exemplar fields are corrected, not obeyed:** `storage.sizeClass` → `storageClass` (the
   former does not exist in the 1.30 CRD and the API server prunes unknown fields, so the exemplar
   would have silently used the cluster's default StorageClass — correct by accident here, wrong
   anywhere else); `monitoring.enablePodMonitor: true` → `false` (a `PodMonitor` needs the
   Prometheus Operator CRDs that arrive in Phase 9, so leaving it on would fail every
   reconciliation); and the placeholder `imageName` → a digest pin (I-5).
9. **The schema's canonical home is the phase subtree.**
   `deploy/phases/05-postgres/migrations/001_create_tables.sql` is applied by this phase's
   migration Job through a kustomize-generated ConfigMap. ARCHITECTURE §3.3 had named
   `enrichWorker/migrations/001_create_tables.sql`, a path that no longer exists; §3.3 is corrected
   in the same change. Phase 7c's enrichWorker consumes this DDL rather than forking its own copy —
   a second schema definition would be the kind of silent divergence I-6 forbids for registries.

**Consequences.** The relational store is reproducible from git alone: one vendored controller,
one Cluster, one ScheduledBackup, one idempotent migration and four NetworkPolicies (three
inherited from Phase 3, two added here). Two consequences deserve to be visible rather than
buried: the backup path deliberately sits on a deprecated-but-supported API with a named exit
trigger, and the single-node anti-affinity decision means "2 instances" is a durability posture on
this substrate, not a topology guarantee — both are restated in the phase's mission-log entry.

---

## ADR-020 — The restore drill lives in git but outside the reconciled tree
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 5

**Context.** PHASES.md §2 Phase 5 requires that "a restore drill into a scratch cluster succeeded",
and OPERATIONS §7 prescribes the shape: apply a restore manifest, verify row counts and the smoke
test. Two rules then pull against each other. I-1 says the cluster is reconciled from git and
nothing is applied by hand; a drill is by nature a bounded procedure whose artifacts must not
survive it. Meanwhile MISSION.md §5's restart-from-scratch test means the drill has to be
expressible from the repository alone — an improvised sequence of commands that lives only in a
chat log is not restartable.

**Decision.** Keep the drill as a **buildable git subtree that Argo deliberately does not
reconcile**: `deploy/phases/05-postgres/restore-drill/`, absent from the phase root kustomization,
applied and deleted as a unit by an operator following OPERATIONS §7. Applying it is recorded as
sanctioned imperative exception 5 (§9.5) — the same class as the git-transport advance
(ADR-018 §1): a bounded, documented operator action that the reconciler cannot express, executed
against a tree that is still the single source of truth.

**Alternatives rejected.**
1. *A permanently reconciled scratch cluster.* It would hold a second PostgreSQL cluster running
   for the life of the platform against the mission's tightest resource (risk R1), and it would
   restore exactly once — after which it demonstrates nothing about any newer backup. A drill that
   cannot be re-run is not a drill.
2. *No manifests in git; run the drill imperatively.* Cheapest in the moment and the worst long
   term: it re-invents the procedure for each operator, which is precisely what the
   restart-from-scratch test exists to catch.

**Consequences.** The drill is reproducible from the repository, leaves no permanent footprint, and
its evidence is the verify Job's own exit status rather than a human's judgement: the drill writes
a canary row into the source, takes a fresh base backup, restores into the scratch cluster, and
then connects **as the application role with the application's sealed password** to assert the
schema, the canary, and that the SECURITY §3.3 grant matrix survived the round trip. Because the
drill runs outside Argo, its objects are not pruned automatically — the documented procedure ends
with an explicit delete, and a forgotten drill is visible as two Clusters in
`kubectl get cluster -n nagar-platform`.

## ADR-021 — Ollama model provisioning: shared PVC staged by a checksum-gated Job
**Status:** Accepted · **Date:** 2026-09-29 · **Phase:** 6

**Context.** Phase 6 needs 2.52 GB of model weights (bge-m3, qwen3:1.7b) inside an air-gapped
cluster (ADR-010 forbids runtime pulls), delivered to an ollama StatefulSet. The natural
StatefulSet shape — a `volumeClaimTemplate` — creates the volume *with* the pod, but the volume
is empty on first start: nothing can populate it before the StatefulSet exists, and a Job cannot
mount a claim that does not yet exist. A weight-download sidecar violates ADR-010 at runtime, and
a per-model PVC multiplies the seeding problem.

**Decision.** Provision models as a **Job that populates a standalone shared PVC**
(`ollama-models`, RWO, 10 Gi) which the ollama StatefulSet then mounts. The payload image
`mission/ollama-models` carries the weights copied from the host (where they were pulled once,
online) plus a `models-manifest.sha256` committed to git; the image build runs `sha256sum -c` as
a gate, and the in-cluster Job verifies the checksums a second time before restoring them into
the PVC and probing the live server's `/api/tags`. Idempotent by construction: re-running the
Job re-verifies and re-copies over itself. Ordering needs no init-container chain — the Job
completes long before the StatefulSet's first start in practice, and ollama handles an empty
models dir gracefully if the ordering is ever inverted.

**Alternatives rejected.**
1. *`volumeClaimTemplate` + first-boot model pull:* breaks the air gap (ADR-010) — the pod would
   need internet exactly once, which is the one time the guarantee must hold.
2. *Weights baked into the ollama image itself:* conflates the upstream server image with a
   2.5 GB payload; every model change would rebuild and re-verify the server layer (I-5's
   provenance story becomes one blob), and the pinned upstream digest stops meaning anything.
3. *Retain/preload via an init container on the StatefulSet:* a pod template mount cannot
   reference a claim created by that same StatefulSet, and the init container would re-run on
   every ollama restart for no benefit.

**Consequences.** Model payload provenance lives in git (`models/models-manifest.sha256`) and the
registry digest pin records what the cluster actually serves; the Job is the single writer of the
PVC (ollama mounts it read-write for its own runtime state under `/models`, `OLLAMA_KEEP_ALIVE`
keeps the session warm), so a compromised model file is detectable by re-running the checksum
gate. RWO is sufficient on a single-node substrate; if the platform ever spans nodes, this is the
surface to revisit (RWX or per-node staging). The manifests reference this ADR at the point of
deviation.

## ADR-022 — adminService ships 7f without POST /vector/resync

- **Status:** Accepted (2026-09-30)
- **Context:** ARCHITECTURE §4.1 lists four adminService endpoints: `/health/cluster`,
  `/audit-logs`, `/dlq`, `/vector/resync`. The Phase-7f charter's exit criteria name only
  the first three. `/vector/resync` is a POST that triggers schemaIndexer `POST /reindex`,
  which §4.1 itself marks as `internal` — the indexer has no JWT gate of its own, and
  there is no documented service-to-service credential story yet (the edge and TLS arrive
  in Phase 8; the frontend in 7g).
- **Decision:** Implement the three read/inspect endpoints in 7f and defer
  `/vector/resync` to the 7g/Phase 8 window. Do not ship an admin-JWT proxy that
  forwards to an unauthenticated internal endpoint: it would let any holder of an admin
  JWT trigger a collection rebuild while the call chain behind it remains unauthenticated
  — a gate in front of an open door.
- **Consequences:** adminService intentionally implements 3 of the 4 §4.1 rows; the
  handler is absent, not stubbed (no fake 200s). The Phase-7f ledger records the
  deferral. Revisit when 7g (frontend needs a resync button) or Phase 8 (TLS + service
  identity) lands — at that point either give schemaIndexer a real auth story or have
  adminService call it over a mutually-authenticated path.
## ADR-023 — UI tier talks to the cluster through a server-side BFF; injector proxies ingestion

- **Status:** Accepted (2026-09-30)
- **Context:** ARCHITECTURE §4.1 gives the browser services no cross-origin story before
  Phase 8 (CORS middleware lands with the edge). The legacy frontend called
  `NEXT_PUBLIC_*` URLs directly from the browser and carried an obsolete `user_id`
  login field; SECURITY §6.2 lists no UI-held secrets; the vault-ui injector needs to
  reach ingestion (5173 injector → 3000 API) but ingestion serves no CORS either.
- **Decision:**
  1. The frontend (3001) is a **server-side BFF**: the browser talks only to :3001;
     Next route handlers (`/api/login`, `/api/whoami`, `/api/ask`) forward to
     authService/slmService with the session cookie relayed as `Bearer <token>`;
     login bodies are whitelisted to `{username, password}`; the Set-Cookie is
     re-emitted host-only/httponly/path=/; `/ask` responses are whitelisted to
     `{sql, rows, row_count, role}`. The UI holds zero secrets; no browser-visible
     service DNS names; every backend contract is enforced server-side.
  2. The vault-ui injector (5173, dev overlay, never edge-exposed) **proxies** the
     ingestion calls server-side over a fixed method+path allowlist, with credential
     headers redacted from logs. Its operator stages an ephemeral session token at
     pod `/tmp/injector-token` (shredded after use) — the browser never holds it.
  3. Both UI pods keep exactly two dependency egress flows (frontend → auth+slm;
     injector → ingestion) plus DNS, matching SECURITY §8's enumeration.
- **Consequences:** browser JS never sees a bearer token or a backend hostname; CORS
  work in Phase 8 shrinks to the frontend origin only; the BFF is an extra hop for
  media flows (7g UI does not yet exercise presigned PUTs — noted for Phase 8 browser
  E2E). Legacy `NEXT_PUBLIC_*` URL configuration is retired.
## ADR-024 — Phase 8 edge: in-cluster Traefik behind a LoadBalancer Service; k3d.nagar.internal as the single edge hostname

- **Status:** Accepted (2026-09-30)
- **Context:** k3s's bundled Traefik was disabled at cluster creation by design ("no traefik pods
  (disabled by design, edge lands in Phase 8)" — G0). Phase 8 (PHASES.md §2) requires Traefik
  IngressRoutes with the frozen port map (`/`→frontend, `/api`→ingestion, `/auth`→auth,
  `/admin`→admin), cert-manager internal-CA `Certificate`s, a CORS middleware, and a rate-limit
  middleware. Risks R3 (host network/DNS) and R4 (host ports 3000–4005 occupied) constrain host
  exposure: the mission log commits to "edge access via ephemeral load-balancer mappings".
  The host currently listens on neither 443 nor 80.
- **Decision:**
  1. **In-cluster Traefik deployment** (not k3s's daemonless builtin, which cannot do
     IngressRoutes/middlewares) in `nagar-system`, image `mission/traefik:v3.5` from the internal
     registry (digest e157892e…), non-root container securityContext, no hostPath mounts, no
     wildcard RBAC (reads IngressRoutes/Middlewares/TLSOptions/Secrets/Services/Endpointslices
     in the mission namespaces only).
  2. **Exposure: `Service type=LoadBalancer` publishing port 443 only.** On k3d the serverlb
     proxies it to an ephemeral host port; HTTPS access is via `https://k3d-nagar.localhost`
     resolved through the existing k3d registry alias entry in the host's hosts file (the
     registry is already reachable at `k3d-nagar.localhost:35000` — same hostname, no new DNS).
     In-cluster callers keep cluster-internal paths; the edge is for the browser/host only.
  3. **One edge hostname, `k3d.nagar.internal` as the documented production name and
     `k3d-nagar.localhost` as this substrate's alias for it** — the Certificate covers both SANs
     (DNS.1 `k3d.nagar.internal`, DNS.2 `k3d-nagar.localhost`). No wildcard certificates.
  4. **TLS: cert-manager self-signed ClusterIssuer `nagar-edge-ca`** (bootstrap pattern: the
     issuer signs its own CA cert from a generated self-signed Secret) issuing
     `edge-tls` (Secret in `nagar-system`, CN `k3d.nagar.internal`, the two SANs above, 2160h).
  5. **Route map (frozen, CONVENTIONS §4):** `/` → frontend:3001; `/api` → ingestion:3000;
     `/auth` → auth:4000; `/admin` → admin:4001 (admin JWT enforced upstream per SECURITY §3);
     `/minio` → minio:9000 (browser presigned PUT route only). Explicitly NOT routed:
     queryService/slmService/schemaIndexer (cluster-internal only), vault-ui 5173 (dev overlay).
  6. **Middlewares:** `edge-headers` (security headers on every router), `edge-cors`
     (headers middleware: allow-origin regex `https://(k3d\.nagar\.internal|k3d-nagar\.localhost)`,
     the documented methods/headers, `accesscontrolallowcredentials=true`, preflight
     `maxAge: 600`) attached ONLY to the `/minio` router (matches the browser behavior that
     actually needs CORS: direct presigned PUTs); `edge-ratelimit` (RateLimit: average 10,
     burst 20, period 1m — below the auth in-app limit of 5/min, i.e. defense-in-depth that
     fires first) attached to `/auth/login`. No StripPrefix anywhere: upstreams keep their
     native paths; the frontend BFF path map is UNCHANGED (a second, prefix-stripped frontend
     route would break its host-only cookies across `/` vs `/auth` — so the smoke script's
     `/auth/login` is exercised as a documented alias in the browser flows only; the BFF keeps
     using its in-cluster upstreams).
     **Correction (2026-09-30, G8 E2E — the "No StripPrefix anywhere" claim above is
     live-FALSIFIED):** upstreams serve their native paths and do NOT self-strip, so the edge
     strips the routing prefix wherever it differs from the upstream's own: `/auth`, `/admin`,
     `/minio` carry StripPrefix (auth natively serves `/login`/`/whoami`/`/create`/`/logout`,
     admin `/health/cluster`/`/dlq`/`/audit-logs`, MinIO S3 paths); `/` and `/api` remain
     VERBATIM (ingestion natively serves `/api/v1/…`, frontend at root). Proven in G8.4/G8.6:
     a presigned PUT through `/minio/<bucket>/<key>` reaches MinIO (200 + ETag + byte-identical
     object), and `/api/v1/...` arrives untouched (ingestion's native JSON 404). The BFF keeps
     its in-cluster upstreams regardless, so the cookie concern above never touches the
     stripped routes. `edge-ratelimit` in fact attaches to the whole `/auth` router
     (PathPrefix(`/auth`)), not `/auth/login` alone — G8.3 shows it counting login attempts.
  7. **Phase-8 in-cluster env flips:** auth `COOKIE_SECURE=true` (§2: mandatory once TLS
     terminates at the edge; in-cluster logins come through the edge hostnames, so cookies must
     carry Secure to be honored in a TLS browser context) — applied as a patch inside THIS
     phase's tree touching the 7a Deployment env only (cross-phase precedent, recorded here).
- **Consequences:** the edge is a normal reconciled workload (drift-clean, digest-pinned);
  TLS is terminated only at Traefik; in-cluster services keep talking to each other directly
  (their NetworkPolicies unchanged); deleting `deploy/phases/08-edge/` rolls the edge back
  without touching any app phase. Traefik's dashboard is NOT exposed. MinIO keeps its
  `namespace + nagar-app` ingress posture and gains only the nagar-system Traefik flow on 9000.
- **Field repairs (2026-09-30, G8.3):** bring-up exposed three live defects, each fixed through
  git (I-1) rather than imperative mutation: (a) Traefik's ping endpoint must ride a DEDICATED
  plaintext entrypoint (`--entryPoints.ping.address=:8082` + `--ping.entrypoint=ping`, probes
  moved to it): on the deployed build (3.5.6, sha256:e157892e…) attaching ping to the TLS
  entrypoint makes `/ping` 404 while the entrypoint otherwise serves — reproduced on plain
  Docker, so it is image behavior. (An earlier k3s-EPHT/manPage hypothesis was tested against
  the pinned image and falsified — `--ping.manpage=false` is rejected by this build and was
  removed; recorded here so the wrong theory does not resurface as fact.)
  (b) the `traefik-edge` NetworkPolicy needed port-scoped API-server egress (443/6443, no peer —
  the Phase-4 `allow-kafka-api-egress` pattern): without it the kubernetescrd provider's
  reflectors get `connection refused` and the container exits on cache-sync timeout;
  (c) the vendored cert-manager v1.16.4 bundle pins `--leader-election-namespace=kube-system`
  while its leader-election RBAC exists only in the `cert-manager` namespace, so no controller
  could ever take the lease and Certificates sat unreconciled (empty `.status`) —  overridden to
  `cert-manager` via `deploy/phases/01-substrate/cert-manager/cert-manager-le-args-patch.yaml`;
  this is a Phase-1 vendoring defect repaired inside the Phase-1  subtree; (d) the §7
  COOKIE_SECURE flip was attempted twice and both kustomize forms are falsified: a JSON6902
  target in 08-edge is silently INERT (kustomize cannot patch objects outside its build — no
  error, no effect), and a duplicate `auth-service` Deployment document is invalid under
  ServerSideApply (empty image merges over the live object: `image: Required value`, failing
  the phase8-5 sync five times with a SharedResourceWarning). Landed instead as the ADR-024
  §7-sanctioned cross-phase amendment in the 7a manifest itself (`COOKIE_SECURE: "true"`),
  where the object lives — patch as data is impossible across phase trees; the amendment is
  a one-line value flip recorded in the 7a file and here.

## ADR-025 — Browser presigned PUTs are minted on the public edge origin under `/minio`

- **Status:** Accepted (2026-10-01)
- **Context:** The Phase-8 charter's exit criterion is “**browser presigned PUT works from the
  frontend origin**” (PHASES.md §2 Phase 8), and ARCHITECTURE §3.2 has the browser PUTting bytes
  directly to MinIO with CORS from the Traefik middleware. The Phase-8 gate run recorded the
  blocker: 7e's presigner signs against `MINIO_URL`
  (`minio.nagar-platform.svc.cluster.local:9000`) — cluster-internal DNS no browser can
  resolve — and the Deployment offered no external-host setting, so Gate 4 could only prove an
  *equivalent* in-pod minted URL. The ledger named `PRESIGN_PUBLIC_URL` as the closing
  follow-up.
- **Decision:**
  1. 7e gains `PRESIGN_PUBLIC_URL` (browser-facing edge origin, e.g.
     `https://k3d.nagar.internal`; **unset = legacy in-cluster URLs**, so the default surface is
     unchanged) plus an optional `PRESIGN_ROUTE_PREFIX` (default `/minio`, the frozen
     ADR-024 §5/§6 route).
  2. When set, **presigning uses a second S3 client whose endpoint is `PRESIGN_PUBLIC_URL`**.
     This is load-bearing: SigV4 binds the signature to the signed `host`, so the *signer*, not
     a URL-rewriting client, must target the edge hostname. MinIO sees the preserved `Host`
     through Traefik (`passHostHeader` default true).
  3. The returned URL's path gains the route prefix (`/minio/<bucket>/<key>`). That insertion
     is **signature-neutral**: the edge `edge-strip-minio` middleware hands MinIO exactly the
     MinIO-native path the signature was computed over, so MinIO verifies what was signed.
  4. All read paths (`statObject`, `minioOk`) and the unset default keep using the in-cluster
     `MINIO_URL` client — only URL *minting* changes.
- **Consequences:** the browser can PUT the API-returned URL verbatim (through the edge, CORS
  evaluated by `edge-cors`), no client-side URL surgery; the Phase-8 charter deviation is
  closed and re-proven from the host (mission log, G8C). Deployment-specific origin, not a
  secret. `PRESIGN_PUBLIC_URL` is the only new required knob; no port/topic/bucket names change
  (I-6 untouched). Inherent trade-off, recorded: an in-cluster client can no longer PUT the
  API-minted URL (public host + public signature) — in-cluster media fixtures must re-mint with
  the SDK against `MINIO_URL` (the 7e E2E harness does exactly that; the harness previously
  consumed the API URL verbatim, which only worked while the URL was in-cluster).
- **Alternatives rejected:** serving the URL host from `MINIO_URL` and rewriting host+path in
  the frontend (falsifies the signature and hides the contract in a UI); pointing
  `MINIO_URL` itself at the edge (breaks statObject/health and widens NetworkPolicy); a second
  API field with an internal URL (extra capability token with no browser consumer).

---

## ADR-026 — Phase 9 observability: hand-authored manifests, API-based log collection, edge-derived service signals

- **Status:** Accepted (2026-10-02)
- **Context:** ADR-011 chose "kube-prometheus-stack + Loki". That chart cannot be used as-is
  here: ADR-002 forbids Helm in deployment paths (the repo's pattern is vendored, digest-pinned
  install manifests), the kube-prometheus-stack render assumes its own operator CRDs, node
  exporter and a resource budget several times what this 16 GB host affords, and a large part of
  its output (node/cAdvisor coverage, hundreds of bundled dashboards) is not needed for the
  phase's exit criteria (dashboards populated, one alert fired with its runbook, restore drill
  evidenced). Two live facts also shaped the build: (a) PSS `restricted` — enforced in every
  mission namespace — rejects `hostPath` volumes outright, so a file-tailing log collector is not
  admissible in any form; (b) no mission service exposes `/metrics`.
- **Decision:**
  1. **Manifests, not a chart or operator.** Prometheus, Alertmanager, kube-state-metrics,
     Grafana, Loki, Alloy and kafka-exporter are declared directly in
     `deploy/phases/09-observability/`, single-replica, digest-pinned, with resource
     requests/limits sized for the host. Alert rules are Prometheus rule files (`runbook_url`
     anchors per I-7), not `PrometheusRule` CRs; scrape configuration is a hand-written
     `kubernetes_sd` config that names every job's namespace, pod label and port explicitly.
     ADR-011's *substance* (Prometheus metrics, Loki logs, Jaeger deferred) is unchanged.
  2. **The edge exposes its own metrics on the existing `ping` entrypoint.** One added
     `--metrics.prometheus.entryPoint=ping` flag in `deploy/phases/08-edge/traefik-deployment.yaml`
     (a recorded cross-phase amendment, same precedent as ADR-024 §7 / ADR-025): `/metrics`
     answers on :8082 next to `/ping`, so **no new port enters the edge's frozen registry** and
     the phase-9 NetworkPolicy widening (`allow-prometheus-scrape-traefik`) is the only other
     change the scrape needs.
  3. **Log collection tails the API, not the node filesystem.** Grafana Alloy
     (`loki.source.kubernetes` + RBAC on `pods/log`) replaces Promtail, which cannot run under
     PSS restricted. Cost, stated: the API server streams pod logs instead of the node reading
     its disk — acceptable at single-node scale and revisited if the cluster grows. Related
     deferrals, recorded rather than hidden: `verifyImages` (no signed images exist until the
     Phase 10 supply-chain pass), the optional `policy-reporter` UI (Kyverno's native
     PolicyReports + metrics cover reporting), and app-tier `/metrics` — until a service exposes
     one, `Ingest5xxRate` is computed from Traefik's service counters and SECURITY §8's
     `nagar.io/scrape` convention is labeled unfulfilled.
  4. **New ports are registered, not invented at the edge.** Grafana listens on **3300** (its
     image default 3000 is already the ingestion API's registered port), and CONVENTIONS §4
     gains the observability rows plus the two pre-existing metrics ports (cert-manager 9402,
     CNPG 9187). Nothing in this tier is exposed through Traefik.
- **Consequences:** Phase 9's exit criteria are met with a stack that fits the host; dashboards,
  rules and scrape configs are all git-owned and Argo-pruned; the Kyverno "full set" is
  enforce-mode where the cluster is compliant today (nagar-app/nagar-observability) and
  audit-mode in `nagar-platform` until the CNPG operator's image is pinned/signed.
- **Alternatives rejected:** vendoring the kube-prometheus-stack render (fails ADR-002's spirit and
  the RAM budget; drags an operator that duplicates CRDs this repo does not otherwise use);
  Prometheus Operator CRDs without the chart (still an operator + CRDs for one replica's worth of
  config); running Promtail in a non-mission namespace or with a PSS carve-out (SECURITY §5's
  namespace-wide posture is worth more than the API load it saves); instrumenting every service
  for `/metrics` inside this phase (cross-phase code churn across six services; deferred with the
  edge-derived substitute named above).

---

## ADR-027 — At the edge the console BFF owns `/api/{login,whoami,ask}`; ingestion owns `/api/v1`

- **Status:** Accepted (2026-10-03) · **Phases:** 8 (edge tree) · 10 (cutover gate)
- **Context:** ADR-024 §5 froze the edge route map as `/`→frontend:3001, `/api`→ingestion:3000,
  `/auth`→auth:4000, `/admin`→admin:4001, `/minio`→minio:9000, with slmService explicitly *not*
  routed. Phase 10's entry gate — the first end-to-end run of OPERATIONS §11 — falsified two
  assumptions of that map on the live cluster:
  1. **step 5's literal `POST /ask` has no edge route.** `/ask` falls through to the frontend's
     `/` catch-all (Next.js 404), and by §5's own decision slmService is not routed at all. The
     console's real ask surface is the frontend BFF's `POST /api/ask` (ADR-023), whose BFF
     forwards to slmService in-cluster.
  2. **the console's BFF routes are shadowed.** the `edge-frontend` router (which matches every
     path) and the `edge-ingestion` router (which matches every `/api` path) both match
     `/api/login`, and Traefik's longest-rule
     tiebreak (the behaviour `ingressroutes.yaml`'s own header comment records from G8.3) picks
     ingestion. Raw evidence, host → `kubectl -n nagar-system port-forward svc/traefik-edge`:

     ```
     GET  https://k3d.nagar.internal:<port>/login        -> 200 (console renders the login page)
     POST https://k3d.nagar.internal:<port>/api/login    -> 404 "Cannot POST /api/login" (ingestion)
     POST https://k3d.nagar.internal:<port>/api/ask      -> 404 (ingestion)
     POST https://k3d.nagar.internal:<port>/ask          -> 404 (frontend Next.js catch-all)
     POST http://127.0.0.1:<pp>/api/login (svc/frontend) -> 401 {"detail":"invalid credentials"}
     ```

     The officer console is therefore served at the public edge but cannot authenticate there —
     while CONVENTIONS §4 assigns :3001 "ingress `/` (public edge)" and ADR-023 made the browser
     talk to that origin exclusively. Steps 1–4 and 6 of §11 were unaffected (`/auth/` 200,
     `/api/v1/events` 401, `/admin/health/cluster` 401 are their documented auth walls).
- **Decision:** the edge routes by *owned path prefix*, not by a bare `/api` catch-all:
  - **`/api/v1/**` → ingestion:3000 — unchanged.** That is the frozen endpoint registry of
    ARCHITECTURE §4.1 (presign, events), so ingestion keeps every path it owns, and the catch-all
    under `/api` still lands on ingestion for anything not named below.
  - **`/api/login`, `/api/whoami`, `/api/ask` → frontend:3001** via a new `edge-frontend-api`
    IngressRoute in `nagar-app`, each route carrying an explicit `priority: 1000` — Traefik's
    default priority is rule length, which is what let the shorter `/api` rule win in the first
    place. `/api/login` additionally carries `edge-ratelimit`: once the path is reachable, the
    per-client edge limiter is what keeps the auth tier's 5/min in-app limiter (SECURITY §2)
    keying on the real client IP instead of on the BFF pod.
  - **ADR-024 §5 is otherwise unchanged:** `/`, `/auth`, `/admin`, `/minio` as before;
    slmService/queryService/schemaIndexer stay cluster-internal (the BFF remains the only
    browser path to `ask`); no StripPrefix is added, so the §6 note about host-only cookies
    across stripped routes still holds — the console now uses a single origin for page and API.
- **Consequences:** §11 step 5 is literally satisfiable as "ask via edge"
  (`POST /api/ask` → `{sql, rows}`), and the console logs in through the public edge. The frozen
  map's "frozen" scope is restated as *path ownership per service* — which this change preserves —
  rather than a literal `/api` prefix claim, which it corrects. Reverting `edge-frontend-api`
  restores the previous behaviour exactly: the console renders but cannot authenticate at the
  edge. Reaching slmService directly at the edge stays explicitly out of scope; the BFF is the
  documented surface (ADR-023).

---

## ADR-028 — schemaIndexer reindex verifies searchability and rebuilds corrupt collections

- **Status:** Accepted (2026-10-03) · **Phases:** 6 (indexer tree) · 10 (entry gate)
- **Context:** OPERATIONS §12.33 records a recurring Qdrant failure: a segment goes corrupt
  (`OutputTooSmall { expected: 4, actual: 0 }` at search time) while `/collections/<name>` still
  reports `status: green` and `/health` reports every dependency ok, so slmService `/ask` 503s
  with "retrieval or generation backend unreachable". Seen at G7d.4 and G7g.2; the Phase-10 entry
  gate found the **third** occurrence, and this time the documented recovery did not work:
  `POST /reindex` returned `{"status":"ok","documents":40,"upserted":40,"points_count":40}` while
  `/points/search` stayed **500 on 12/12 probes**. Root cause: `ensure_collection` was idempotent
  on the vector **dimension** alone, so it kept the existing collection — including the corrupt
  segment — and re-upserted 40 points into it. The collection showed `segments: 2` (one healthy,
  one corrupt); the healthy segment is what `/points/query` reached, which is why that endpoint
  answered 200 while the `/points/search` path slmService uses did not. The prior recoveries
  "worked" only because they happened to coincide with a qdrant restart.
- **Decision:** the indexer owns collection health, not just point counts.
  1. `search_ok()` probes the **read path** (`POST /collections/{c}/points/search`) — the same
     call slmService makes — instead of trusting collection metadata.
  2. `ensure_collection` drops and recreates the collection when the dimension differs **or**
     the collection cannot serve a search, so a corrupt segment is actually evicted. This is
     correct because `nagar_schema` is a **rebuildable cache** (40 chunks from
     `schema_docs.json`), never durable data (ADR-021-adjacent; §12.33 already says so).
  3. `sync()` read-after-writes: after upserting it searches with a real document vector and
     raises if the collection still cannot serve, so a failed recovery can no longer be
     reported as `200 ok`.
  4. `/health` reports `searchable` and folds it into `healthy`, so the endpoint stops claiming
     health while `/ask` is down.
- **Consequences:** §12.33's recovery now converges in one call instead of needing a pod
  restart; a corrupt-segment recurrence becomes self-healing on the next `/reindex` or indexer
  start (the Job runs `--once`, the Deployment serves `/reindex`). Cost: one extra search request
  per reindex and per `/health` poll. Reverting the probe restores the silent-success behaviour
  that produced the G10.1 stall. Note the corruption itself is not explained by this ADR — a
  third occurrence in the same substrate is worth a follow-up on Qdrant storage/pressure, and the
  `searchable` signal is what would surface it.

---

## ADR-029 — enrichWorker emits media columns only for the tables whose DDL carries them

- **Status:** Accepted (2026-10-03) · **Phases:** 7 (worker tree) · 10 (parity checklist)
- **Context:** the Phase-10 parity checklist requires "all 5 dept tables written", so G10.2
  exercised **all five** department topics for the first time — every earlier gate had used
  `complaints` (and `traffic`) only. The first `water.sensors.raw.v1` event crashed the consumer:

      psycopg.errors.UndefinedColumn: column "media_bucket" of relation
      "water_sensor_readings" does not exist
      … File "/app/enrich.py", line 240, in run_consumer
          verdict = process_message(msg.topic(), msg.value())

  `build_upsert` emitted `media_bucket`/`media_object_key` for **every** table, but migration 001
  defines those columns on `nmc_complaints` and `traffic_events` only. The exception escaped the
  consumer loop and killed the worker process, so `enrichWorker` entered `CrashLoopBackOff` and
  every department after the first bad one stayed unenriched — a single malformed assumption
  taking the whole enrichment tier down. `water` and `health` had **never** been written by any
  gate in this mission.
- **Decision:** the column list is derived from the table, not assumed. A `MEDIA_TABLES` set
  (`nmc_complaints`, `traffic_events`) mirrors migration 001 and the media columns are appended
  only for those tables; the parameter tuple is built the same way so the two lists cannot drift.
  A regression test asserts the media columns appear **only** where the DDL has them, and that
  the emitted column count always equals the parameter count for all five tables.
- **Consequences:** all five departments enrich. The guard is the general one — "the upsert's
  column list must match the DDL" — so adding a sixth table or a new column now fails a test
  instead of a pod. Shipped as `phase7c-2` (digest `5bad93aa…`). Note the deeper issue this
  exposed and did not fix: a per-message DB error currently terminates the process, which is
  why one bad event took down the tier. Routing an unexpected DB error to the DLQ (or restarting
  the poll loop without exiting) is the follow-up, deliberately not bundled here.
- **Amendment (2026-10-04, G11):** the named follow-up landed. `process_message` now quarantines a
  data-level `psycopg.Error` to the DLQ and acknowledges the message, while connection-level
  failures (`OperationalError` / `InterfaceError`) still propagate so a DB outage is never drained
  into the DLQ. Reproduced live first (an `occurredAt` the DB rejected CrashLooped the worker,
  `nmc.complaints.raw.restricted.v1` LAG stuck at 1) and re-proved after shipping `phase7c-3`
  (`-> db-error`, restarts 0, LAG 0, the message in the DLQ). This ADR's decision is unchanged; the
  deferred consequence is now closed.


## ADR-030 — PII is enforced at two independent layers: a shape gate and column-level grants

- **Context:** an audit of `queryService` found the PII denylist (SECURITY §3 layer 4) matched
  denylisted *column names* only. A `nmc_officer` could therefore reference the PII table itself
  and receive every column, PII included: `SELECT c FROM nmc_complaints c`,
  `SELECT to_jsonb(c) …`, `row_to_json`, `json_agg`, `array_agg`, `to_jsonb(c.*)`. None of these
  contains a denylisted identifier, so all of them passed the gate. There was no second line of
  defence: migration 001 granted `SELECT` at **table** level, so the database would have returned
  `name`, `phone`, `email`, `address` and `aadhaar` to any role holding that grant. A single
  application-layer matcher stood between an officer and citizen PII.
- **The backstop was inert until the wall was fixed.** Applying the column grants to a
  live PostgreSQL and then running queryService against it showed the statements executing
  as `postgres`, not `nmc_officer`: `wall_begin` issued `SET ROLE` on a connection it then
  closed, and the query ran on a fresh one. In production the connecting role is `nagar`,
  which **owns** every warehouse table — an owner bypasses column-level grants outright, so
  ADR-030's layer 2 would have blocked nothing. Layer 1 (the AST gate) was the only control
  actually in force. `SET ROLE`, the statement and `RESET` now share one connection, and the
  role is asserted in tests rather than assumed.
- **Decision:** two independent layers, and neither is trusted alone.
  1. **Shape gate (primary).** The denylist is no longer a name blacklist; the projection must be
     *proven column-by-column*. A reference to a PII table or any alias of it (in any subquery) is
     a whole-row reference and is blocked, as is any `*` over a PII table wherever it appears. The
     sole exemption is an argument of a scalar-collapsing aggregate (`count`, `sum`, `avg`, `min`,
     `max`, …), which cannot emit a column — this preserves the `COUNT(*)` carve-out the Phase-7d
     E2E needed. Serialising wrappers (`to_json`, `json_agg`, `array_agg`, `string_agg`, …) are
     deliberately **not** exempt.
  2. **Column grants (backstop).** New migration `002_pii_column_grants.sql` revokes the
     table-level grant and grants `SELECT (<every non-PII column>)` to `nmc_officer` and
     `health_officer`. The column list is derived from `information_schema` minus the denylisted
     names, so it cannot drift when the DDL changes.
- **Consequences:** a query that slips past the gate can no longer return PII. A database denial
  is therefore a normal control outcome, not an outage: `InsufficientPrivilege` is caught and
  reported as an audited `403 db-wall` (it previously fell through to `503 database unreachable`,
  which would have mislabelled a security decision as a readiness failure). Getting there took
  two attempts: the first still returned 503, because `RESET ROLE` in a `finally` ran inside the
  aborted transaction and raised `InFailedSqlTransaction`, masking the real error. `RESET` is now
  on the success path only — the connection is per-request and cannot leak the role. Separately, this
  pass found the RBAC table set counted CTE **aliases** as tables — blocking legitimate CTE
  queries while a CTE named after an allowlisted table could smuggle a data-modifying statement
  past the gate; DML nodes are now rejected anywhere in the AST and aliases are subtracted.
  **Deliberate I-9 exception:** a Phase 7b fix landed in the Phase 5 subtree, approved by the
  owner. Recorded here so the isolation rule is not silently broken.
- **Not decided here:** whether the denylist list itself should move into configuration, and
  whether `health_camp_records` needs the same treatment once it carries identifiable columns.

## ADR-031 — Port 9418 (git transport) is registered, closing an I-6 registry drift

- **Context:** the port registry (CONVENTIONS §4, frozen under invariant I-6) had no row for the
  git transport the Phase-2 Argo CD install actually publishes. `git-repo-mirror` serves `9418`
  (`git daemon`) in `nagar-system`, so the platform shipped a first-party port that the contract
  did not know about. Every other unregistered port in the tree belongs to a vendored third-party
  controller (Kyverno 8000/9443, cert-manager 6080/9403/10250, Argo CD 5556-5558/7000/8083/8084,
  CNPG 9443) and is out of scope by design.
- **Decision:** register `9418 | git-repo-mirror (git daemon) | nagar-system only — Argo CD's
  repo transport, never exposed at the edge` in CONVENTIONS §4.
- **Consequences:** the registry is whole again. Changing this port remains an ADR. The audit
  that produced this entry ran as a rendered-manifest census of every `Service` and
  `containerPort` in all 41 trees against §4, which is now the check to re-run whenever a
  manifest adds a Service.

---

## ADR-032 — `ttlSecondsAfterFinished` is prohibited on Argo-managed Jobs

- **Context:** every Argo-managed init Job set `ttlSecondsAfterFinished` (`bucket-init` 86400,
  `nagar-kafka-topics` 86400, `nagar-db-migrate` 3600, `nagar-ollama-models` 7200,
  `nagar-schema-index` 7200) for retention "without clogging the namespace". The TTL controller
  deletes the completed Job **object**. Argo then compares desired against live, finds the desired
  Job absent, and reports the app `OutOfSync` **at an unchanged revision** — the very revision it
  had already synced. Every app runs `automated.selfHeal: true` with `prune: true`, so Argo
  re-creates the Job and it **re-runs**. The TTL is therefore not retention hygiene; it is a
  re-run trigger on a timer.
- **Evidence (2026-10-06, live).** `nagar-phase6-vector-llm` was `OutOfSync` with
  `nagar-ollama-models` absent; Argo re-created it inside the observed window and the Job re-ran
  end-to-end — checksum verification of all nine model blobs, then `restoring into the shared PVC`,
  a multi-GB write into the claim the live Ollama server reads. Orphaned `Completed` pods with no
  owning Job corroborate earlier cycles (`nagar-ollama-models-lb6kx` 14 h, `nagar-db-migrate-fxt4k`
  13 h, `nagar-schema-index-xgf2d` 14 h). Argo's own auto-sync backoff (`Skipping auto-sync: already
  attempted sync to [<rev>] … retrying in …`) spaces the cycles irregularly, so a single `Synced`
  snapshot can look healthy — the drift is only visible if you watch.
- **Decision:** `ttlSecondsAfterFinished` must not be set on a Job that Argo CD manages. Removed
  from the five Jobs above. The completed Job object is retained indefinitely: it *is* the durable
  evidence, and its absence is what created the loop. Object count is not a concern at this scale.
  Re-running stays a deliberate act — change the spec (which lands through the Job's existing
  `Force=true,Replace=true`) or delete the Job per OPERATIONS §8.
  **Scope:** `deploy/phases/05-postgres/restore-drill/` keeps its TTLs, because that tree is
  deliberately **not** Argo-managed (an operator procedure applied by hand, per its kustomization
  header); there a TTL is genuine cleanup.
- **Consequences:** apps stop flapping `OutOfSync`, which restores `OutOfSync` as a real drift
  signal — the loop had been masking it. Repetition of heavy work stops: the TTL period bounded how
  soon each Job could re-run, so the migration could re-run as often as hourly, the model copy and
  the schema re-embed every 2 h, and the bucket and topic init daily. Idempotency (I-2) is
  unchanged: still required, just no longer exercised on a schedule. This **supersedes ADR-016 §1's**
  claim that the Job "is not re-run on syncs where the spec is unchanged … does not churn (I-2)",
  and **re-attributes** the open item the Phase-4 record raised (mission log, "Honest correction to
  the Phase 3 record"), which blamed `Replace=true`: TTL alone is sufficient, and it was the live
  cause.
- **Convergence caveat, found while shipping this.** Argo's differ does not compare
  `ttlSecondsAfterFinished`. After the mirror advanced to the fixed revision, all four affected
  Applications reported `Synced` while all five live Jobs still carried the old TTL, and the
  controller logged `Skipping auto-sync: application status is Synced`. So a git-side removal
  alone never converges on a Job that already exists. Live state was brought to git state with the
  §8 pattern (delete the Job; Argo recreates it from the TTL-free revision) — the sanctioned
  exception, not a hand-edit — after which all five live Jobs report the field `ABSENT`. Same class
  of normalization as ADR-016 §2(b): the differ is not the source of truth, the manifest is.
- **Still open:** whether `Replace=true` *additionally* re-runs a Job whose spec is unchanged is
  not separated by this evidence — that question remains open in the Phase-4 record. If periodic
  re-indexing is ever wanted as a feature, it belongs in an explicit `CronJob`, never in a TTL
  side effect.
