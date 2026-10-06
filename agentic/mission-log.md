# NagarVault Mission Log

> Append-only journal per MISSION.md §5. Every claim below cites the command run and its output.
> Companion mandate: [MISSION.md](MISSION.md) · Operating guide: [AGENTS.md](../AGENTS.md)
> Branch: `phase/00-mission-baseline` · Day 0 executed: 2026-09-29

---

## Day 0 — Onboarding, environment audit, baseline commit, cluster bring-up

### 0.1 Onboarding summary (in my own words)

NagarVault is a civic-data platform whose defining property is that **the cluster is the only
runtime that matters and git is the only source of truth for it**. Five FastAPI/Express services
and two UIs turn raw civic events (complaints, traffic, water sensors, health camps, EV bus
telemetry) into a queryable warehouse: files go browser→MinIO via presigned PUT (the API never
touches media bytes), event metadata goes through six frozen Kafka topics, `enrichWorker`
normalizes them into five department tables, and officers either run validated SQL through
`queryService` or ask natural-language questions of `slmService`, which does RAG over schema
embeddings (Qdrant) and generates SQL with a local Qwen3 1.7B via Ollama — the LLM never touches
the database directly; its output must pass the same sqlglot/RBAC/PII-denylist gate as a human
query, and every attempt lands in `audit_logs`. One JWT chain (`iss=nagar-auth`,
`aud=nagar-services`, 60-min TTL, jti denylist, argon2id logins) authenticates every hop.

The twelve invariants reduce operationally to: never mutate live state outside git (I-1), make
every init/migration re-runnable forever (I-2), never commit secret material — only SealedSecret
blobs (I-3), never ship a workload without probes/resources/NetworkPolicy (I-4), never an
unpinned image (I-5), never invent a port/topic/bucket/table (I-6, registries are the contract),
never an alert without a runbook anchor (I-7), never a non-obvious choice without an ADR (I-8),
never touch outside a phase's subtree (I-9), never edit the frozen legacy files (I-10, now moot —
they are deleted per ADR-013), never let a manifest depend on internet egress at runtime (I-11),
and never leave a `kustomize build` broken (I-12).

**Day 0 decision (recorded as ADR-013, per owner direction):** the deleted service code is **not
restored** — all nine components will be re-implemented from scratch against the frozen
registries (ARCHITECTURE §4.1–§4.3, SECURITY §2–§3, CONVENTIONS §4/§8). No Compose returns; new
per-service Dockerfiles are retained after cutover as build recipes. The mission runs on a
disposable k3d cluster with a paired local registry.

### 0.2 Environment audit (commands + outputs)

| Check | Command (abridged) | Result |
|---|---|---|
| Host | `uname -a` | MINGW64_NT-10.0-26300 (Windows, Git Bash), x86_64 |
| CPU / RAM | `nproc` / `systeminfo` / `docker info` | 28 CPUs · **16 GB physical, ~5.4 GB free at start · Docker VM sees 8.17 GB (7.6 GiB)** |
| Disk | `df -h .` | C: 952 GB total, 486 GB free |
| Docker | `docker version` | client 29.8.0 / server 29.8.0, WSL2 backend (`desktop-linux` context) |
| kubectl | `kubectl version --client` | v1.36.1 (bundled Kustomize **v5.8.1**) |
| k3d | `k3d version` (installed `~/bin/k3d.exe` from release v5.8.3, HTTP-200-verified) | k3d v5.8.3 / **k3s v1.31.5-k3s1 (default)** |
| kubeseal | `kubeseal --version` (installed `~/bin/kubeseal.exe`, release v0.28.0) | kubeseal version: 0.28.0 |
| kustomize | standalone binary download failed repeatedly (GitHub DNS flakes, `curl` exit 6); `kubectl version --client` shows bundled Kustomize v5.8.1 | **shim**: `~/bin/kustomize` → `kubectl kustomize` (same engine, same version) — recorded as an accepted Day 0 deviation |
| Node / Python | `node -v` / `python --version` | v22.23.2 · 3.12.10 |
| git / openssl / curl | `git --version` etc. | 2.55.0.windows.3 · 3.5.7 · 8.21.0 |
| Port occupancy | `netstat -an \| grep LISTENING` | **3000, 3001, 4000, 4001, 4003, 4004, 4005 all occupied by the host** |
| Source of occupancy | `docker ps` | **15 healthy containers from a legacy Compose stack** (`nagar-postgres`, `nagar-kafka`, `nagar-minio`, `nagar-redis`, `nagar-qdrant`, `nagar-ollama`, all 9 app containers), up 1–10 h |
| WSL memory | `wsl -- cat /proc/meminfo` → MemTotal 7,977,668 kB | WSL VM capped at ~7.6 GiB |

**PENDING USER OK — WSL memory raise.** `~/.wslconfig` was rewritten (backup at
`~/.wslconfig.bak-nagarvault`): `memory=14GB`, `swap=8GB`. It takes effect only after
`wsl --shutdown` + Docker Desktop restart, which was **not executed** (needs explicit user OK;
the host is mid-mission with a live legacy stack). Until applied, the k3d VM shares the current
8.17 GB Docker allocation. Decision log: proceeded at current memory; data-plane phases will
re-evaluate (see §0.4 risks).

**Standing orders honored:** the legacy Compose stack is untouched — it serves as the behavioral
reference for the rebuild and is never mutated by the mission (ADR-013 §5).

### 0.3 Git baseline

- Branch `phase/00-mission-baseline` created from `fix/mission-loop-bugfixes` @ `efb60859`.
- Baseline commit **`21472138`** — `chore(mission): Day 0 baseline — rebuild-from-scratch mandate (ADR-013)`:
  136 files changed, 2,259 insertions, 17,255 deletions. Contains: docs suite + `AGENTS.md` +
  `agentic/MISSION.md` + fresh `.gitignore` (added); all service directories, root
  `docker-compose*.yml`, per-service Dockerfiles, and legacy `.env.example` files recorded as
  deleted exactly as found in the working tree (verified: the 16 staged compose/Dockerfile/.env
  entries are all `D` — nothing re-added); the pre-staged retirements (`piiStorageWorker/`,
  `scripts/`, `docs/MISSION_REPORT.md`, `frontend/frontend/` duplicate) preserved as the owner
  left them; `docs/DECISIONS.md` gains **ADR-013** (sequential after ADR-012, verified
  `grep -n "^## ADR-"` → 001…013); `docs/PHASES.md` carries the rebuild-deviation ledger note
  (§0 item 5) and the Phase 10 deviation bullet (verify-absence, Dockerfiles retained).
- **No push. No force-push.** Pushes require explicit owner approval (MISSION.md §3; standing rule).

### 0.4 Risk list (live, will be appended per phase)

| # | Risk | Evidence | Mitigation / trigger |
|---|---|---|---|
| R1 | **RAM is the binding constraint.** Docker VM = 8.17 GB while the plan's data plane wants 10–14 GB; a 15-container legacy stack already runs on the host | §0.2 audit | `.wslconfig` raise to 14 GB **PENDING USER OK** (restart not executed); slim resource requests; Phase 9 degradation ladder; if pressure shows: checkpoint with owner — stopping (never deleting) the legacy stack only with explicit in-moment approval |
| R2 | All 9 services must be authored fresh; contract drift is the main correctness risk | ADR-013 | Contract-conformance discipline: endpoint/topic/claim/RBAC tables copied from registries; per-service gates; ingestion keeps `npm test`/`npm run check` |
| R3 | GitHub release downloads flaked repeatedly (DNS, `curl` exit 6/000) | §0.2 tooling rows | Pinned releases + HTTP-200 verification; `kustomize` shim fallback recorded |
| R4 | Host ports 3000–4005 occupied | `netstat` §0.2 | k3d cluster exposes **no** host NodePorts; edge access via ephemeral load-balancer mappings chosen in Phase 8 to dodge the occupied range |
| R5 | CPU-only inference: 10–30 s/query expected | OPERATIONS §12.8 | Budgeted in Phase 6/7d gates; documented, not a defect |
| R6 | kubeseal↔controller drift if tool/controller versions mismatch | Phase 1 gate | kubeseal 0.28.0 pinned now; controller pinned to a compatible chart manifest in Phase 1; round-trip gate proves it |

### 0.5 Adjusted day grid (from the approved plan)

| Day | Phases | Gate (PHASES.md §1/§2) |
|---|---|---|
| 0 (done) | Onboarding + baseline + substrate tooling + cluster up | tools verified; baseline commit; k3d + registry live with evidence (§0.6) |
| 1 | Phase 1 substrate + Phase 2 GitOps | 5 ns live; sealed-secret round-trip; app-of-apps reconciles; self-heal reverts a manual mutation |
| 2 | Phase 3 object/cache + Phase 4 messaging | 3 buckets; 6 frozen topics; event round-trips Kafka |
| 3 | Phase 5 relational store | migration idempotent; 2-replica CNPG healthy; backup verified; restore drill to scratch ns |
| 4 | Phase 6 vector/LLM + 7a–7b | both models on PVC; `nagar_schema` = 40 vectors; auth `/login` E2E; query RBAC + audit proven |
| 5–6 | **Phase 7c–7g (doubled: fresh code)** | enrich topic→table; presign→PUT→Kafka E2E; `/ask` SQL+rows; admin endpoints; both UIs browser-tested |
| 6–7 | Phase 8 edge + Phase 9 observability | HTTPS smoke steps 1–2; internal-CA issuance; default-deny complete; Kyverno full set; alert→runbook fired |
| 7 | Phase 10 parity cutover + closure | §11 smoke green; parity checklist signed (7-day drift honestly reported if window short); README final; handover |

---

## Gate evidence — Day 0 cluster bring-up

### G0.1 Cluster + substrate verification

```
$ kubectl config current-context
k3d-nagar
$ kubectl get nodes -o wide
NAME                 STATUS   ROLES                  AGE   VERSION        INTERNAL-IP   OS-IMAGE           KERNEL-VERSION                      CONTAINER-RUNTIME
k3d-nagar-server-0   Ready    control-plane,master   45s   v1.31.5+k3s1   172.19.0.4    K3s v1.31.5+k3s1   6.18.33.2-microsoft-standard-WSL2   containerd://1.7.23-k3s2
$ kubectl get pods -A
kube-system   coredns ... 1/1 Running · local-path-provisioner ... 1/1 Running · metrics-server ... 0/1 ContainerCreating
$ kubectl get sc
NAME                   PROVISIONER             ...        AGE
local-path (default)   rancher.io/local-path   ...        42s
$ kubectl get pods -n kube-system | grep -i traefik || echo "no traefik pods (disabled by design, edge lands in Phase 8)"
no traefik pods (disabled by design, edge lands in Phase 8)
no traefik svc
```

Cluster creation evidence: `k3d cluster create nagar --servers 1 --image rancher/k3s:v1.31.5-k3s1
--registry-use nagar.localhost:35000 --volume C:\\Users\\styli\\.k3d\\nagar-storage:/var/lib/rancher/k3s/storage@server:* --k3s-arg "--disable=traefik@server:0"`
→ `INFO[0014] Cluster 'nagar' created successfully!` — **no volume-mount WARN on the recreate**
(first attempt used an MSYS `/c/...` path, k3d stat-failed it, cluster was deleted empty and
recreated with the `C:\\...` path; nothing was ever deployed to the discarded cluster).
Note: the k3s version is pinned to exactly what `k3d version` reported as its default
(k3s v1.31.5-k3s1), so the image pull is a no-op cache hit.

### G0.2 Registry round-trip (I-11 proof)

```
$ MSYS_NO_PATHCONV=1 docker exec k3d-nagar-server-0 cat /etc/rancher/k3s/registries.yaml
mirrors:
  k3d-nagar.localhost:5000:   { endpoint: [http://k3d-nagar.localhost:5000] }
  k3d-nagar.localhost:35000:  { endpoint: [http://k3d-nagar.localhost:5000] }
$ curl -s -o /dev/null -w "%{http_code}" http://nagar.localhost:35000/v2/    # host reachability
200
$ docker tag busybox:1.37 localhost:35000/mission/busybox:day0 && docker push -q ...
PUSH-VIA-LOCALHOST-OK
$ docker images --digests | grep '^registry '                                # registry server image pinned
registry 2 sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373
```

Registry-stored digest of the probe image (queried from the registry itself):
`sha256:66a6306db78bf2dbf3487f293aa8d6990d8e506fdffab9cc43fe422becf886e4`
(cached in `~/.k3d/day0-probe-digest.txt`).

```
$ kubectl run day0-tag-probe --image=k3d-nagar.localhost:5000/mission/busybox:day0 ... 
$ kubectl run day0-digest-probe --image=k3d-nagar.localhost:5000/mission/busybox@sha256:66a6306d... ...
kubectl wait → both pods condition met
-- tag probe:    IN-CLUSTER-PULL-OK
-- digest probe: DIGEST-PULL-OK
```

**Result: the cluster pulls from its local registry by tag and by digest. Push happens from the
host via `localhost:35000`; pulls use the cluster-side mirror name `k3d-nagar.localhost:5000`.**
This two-name fact (same registry container, published only on 35000) plus the Docker-Desktop
daemon-side `*.localhost` DNS gap are recorded for Phase 7's build pipeline: the kustomize image
rewrite maps `registry.nagar.internal:5000` → `k3d-nagar.localhost:5000` for manifests while the
build host pushes via `localhost:35000`.

### G0.3 Incident notes (kept for the record)

1. Docker-Desktop daemon could not resolve `k3d-nagar.localhost` / `nagar.localhost` ("no such
   host") even though Git Bash resolved them — push path corrected to daemon-loopback
   `localhost:35000`; no config changed, evidence above.
2. MSYS path mangling hit twice: `docker exec … cat /etc/...` (needs `MSYS_NO_PATHCONV=1`) and the
   k3d volume arg (needs Windows-style `C:\\...`). Both solved; commands archived here.
3. `docker push` of a multi-platform-cached image re-hydrated it single-platform, so the stored
   digest differs from the pull-time digest — always read the digest from the registry
   (as done) rather than from local image metadata.

---

## Standup — Day 0

**Done:** onboarding (all 7 mandated readings + ADR-013 written); environment audit; tooling
(k3d 5.8.3, kubeseal 0.28.0, kustomize-shim@5.8.1 beside kubectl 1.36.1); baseline branch
`phase/00-mission-baseline` commit `21472138` (no push); k3d cluster `nagar` live (k3s
v1.31.5+k3s1, local-path default SC, Traefik deferred by design); local registry live with
in-cluster tag+digest pull proven.

**Blocked / pending:** WSL memory raise to 14 GB written to `~/.wslconfig` but **awaiting owner
OK to restart WSL/Docker Desktop** (R1). kustomize standalone binary unfetchable this session —
shim in place, revisit opportunistically (R3).

**Next:** Phase 1 substrate — five namespaces with PSS labels, vendored cert-manager/Sealed
Secrets/Kyverno static manifests into `deploy/third_party/`, baseline Kyverno policies, and the
`nagar-jwt` / `nagar-postgres-app` / `nagar-minio` sealed-secret round-trip (kubeseal ↔
controller-version check happens at that gate).

**Risks:** R1 memory (live), R2 rebuild-contract drift (structural), R3 tool-fetch flakes
(observable), R4 host ports occupied (mitigated: no host NodePorts; Phase 8 edge via LB
mappings outside 3000–4005), R5 CPU inference latency (expected), R6 kubeseal/controller drift
(gated in Phase 1).

---

## Phase 1 — Cluster substrate (2026-09-29)

**Entry checklist (PHASES.md §2 Phase 1):** hardware/registry per OPERATIONS §1 — satisfied on the
k3d local substrate (Day 0 gates G0.1–G0.3); build host tooling verified.

### Deliverables (subtree: `deploy/phases/01-substrate/` + `deploy/third_party/`)

- **Vendored static manifests (ADR-002):** cert-manager v1.16.4 (986,843 B, `HTTP 200` verified),
  sealed-secrets v0.28.0 (`controller.yaml` asset; the `sealed-secrets-controller.yaml` name 404s
  on this release), kyverno v1.13.4 (3,388,412 B). Provenance + image-pin method:
  `deploy/third_party/README.md`.
- **Digest pins (I-5):** all 9 image references resolved via `docker manifest inspect -v` and
  pinned in `deploy/phases/01-substrate/digest-pins/` (kustomize Component). Built output:
  9/9 images `@sha256:`, 0 unpinned.
- **Five mission namespaces** (`nagar-platform`, `nagar-app`, `nagar-observability`, `nagar-system`
  + the bundles' `cert-manager`/`kyverno` namespaces PSS-labeled by patch) — all six enforce
  PSS **restricted v1.31** (enforce/audit/warn).
- **Baseline Kyverno policies** (validationFailureAction: Enforce, background: true):
  `require-nagar-labels`, `disallow-latest-tag` (incl. `=(initContainers)` conditional anchor),
  `require-pod-security-context` (pod-level runAsNonRoot + seccomp, container-level drop-ALL/no-PE,
  requests+limits).
- **SealedSecrets (I-3):** `nagar-jwt`, `nagar-postgres-app`, `nagar-minio` — sealed offline with
  `kubeseal --cert` against the controller cert; plaintext generated outside git, shredded after
  the round-trip (only SHA-256 hashes survive in `agentic/tmp/`).

### Layout decisions (documented, reviewer-facing)

1. Kyverno runs in its **upstream-native `kyverno` namespace** (35 hardcoded namespace refs +
   admission webhook clientConfig; relocation risk >> benefit). Deviation from ARCHITECTURE §1 —
   flagging now; if a maintainer wants nagar-system placement, it needs an ADR + upstream-issue check.
2. Sealed-secrets relocated to `nagar-system` (per ARCHITECTURE §1) — required explicit patches to
   RBAC **subject** namespaces (kustomize transformers do not rewrite subjects).
3. cert-manager stays in its native namespace (bundle ships Namespace + webhook wiring).
4. No PSS exemptions were needed: the three bundles are natively restricted-compliant except for
   missing resources, patched in (see `third_party/README.md` audit).

### Toolchain note (R3 update)

The `~/bin/kustomize` shim hit its limit: kubectl's embedded kustomize refuses cross-root loads
(security loader, not overridable — `loadRestrictions` field itself is rejected by both kubectl's
embedded and the standalone v5.8.1 binary). **winget install Kubernetes.Kustomize → v5.8.1
standalone** succeeded; builds require
`kustomize build --load-restrictor LoadRestrictionsNone <tree>` for the `deploy/third_party/`
references (commented in each kustomization.yaml). Shim removed from the critical path.

### Gate evidence

**G1.1 — five namespaces live with PSS enforced:**

```
$ kubectl get ns --show-labels (abridged)
cert-manager          Active   app.kubernetes.io/part-of=nagarvault,nagar.io/phase=1,pod-security.kubernetes.io/enforce=restricted,...
kyverno               Active   app.kubernetes.io/part-of=nagarvault,nagar.io/phase=1,pod-security.kubernetes.io/enforce=restricted,...
nagar-app             Active   app.kubernetes.io/part-of=nagarvault,nagar.io/phase=1,pod-security.kubernetes.io/enforce=restricted,...
nagar-observability   Active   app.kubernetes.io/part-of=nagarvault,nagar.io/phase=1,pod-security.kubernetes.io/enforce=restricted,...
nagar-platform        Active   app.kubernetes.io/part-of=nagarvault,nagar.io/phase=1,pod-security.kubernetes.io/enforce=restricted,...
nagar-system          Active   app.kubernetes.io/part-of=nagarvault,nagar.io/phase=1,pod-security.kubernetes.io/enforce=restricted,...

$ kubectl apply --dry-run=server  # bare busybox pod in nagar-app (no securityContext)
Error from server (Forbidden): pods "psa-deny-proof" is forbidden: violates PodSecurity
"restricted:v1.31": allowPrivilegeEscalation != false ... runAsNonRoot != true ... seccompProfile ...
```

**G1.2 — sealed-secret round-trip (encrypt → apply → controller unseal → private-key recovery):**

```
$ openssl rand -hex 32|16|16|32            # 4 values, written only outside git
$ kubeseal --format yaml --cert ss-cert.crt < plain.yaml > sealed.yaml   # x3, offline
$ kubectl apply -f deploy/phases/01-substrate/secrets/
sealedsecret.bitnami.com/nagar-jwt created | nagar-minio created | nagar-postgres-app created
$ kubectl get secret -n nagar-app
nagar-jwt Opaque 1 · nagar-minio Opaque 2 · nagar-postgres-app Opaque 1   # controller-unsealed
$ kubectl get sealedsecret -n nagar-app -o jsonpath=...conditions
nagar-jwt: Synced=True · nagar-minio: Synced=True · nagar-postgres-app: Synced=True
$ kubectl get secret -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > key-backup.yaml   # OPERATIONS §7 drill artifact
$ kubeseal --recovery-unseal --recovery-private-key key-backup.yaml < sealed.yaml
$ python: base64-decode each data key → sha256 → compare to generation-time hashes
jwtSecret: HASH MATCH · databaseUrl: HASH MATCH · accessKey: HASH MATCH · secretKey: HASH MATCH
ROUND-TRIP-VERIFIED: 4/4
```

Notes: v0.28.0 kubeseal has no `--recover`; recovery = `--recovery-unseal` + exported controller
key, which doubles as the §7 key-backup drill. Plaintext, cert, and backup shredded post-verify
(`agentic/tmp/` retains only the 4 SHA-256 hashes). Key backup was ephemeral for this disposable
cluster — production posture: encrypted offline vault (documented risk in the handover report).

**G1.3 — Kyverno actively enforcing:**

```
$ kubectl get cpol
disallow-latest-tag            true   true   True   Ready
require-nagar-labels           true   true   True   Ready
require-pod-security-context   true   true   True   Ready

$ # deny-proof: compliant securityContext but NO nagar labels → BLOCKED
Error from server: admission webhook "validate.kyverno.svc-fail" denied the request:
require-nagar-labels: check-part-of-label ... check-phase-label ...
require-pod-security-context: restrict-pod-security-context failed at /spec/securityContext/runAsNonRoot/

$ # allow-proof: labels + full restricted context + resources → server dry run ACCEPTED
pod/kyverno-allow-proof created (server dry run)

$ kubectl get pods -A (substrate controllers)
cert-manager ×3 1/1 Running · kyverno ×4 1/1 Running · sealed-secrets-controller 1/1 Running
```

**Policy iteration honesty note:** the allow-proof initially failed through
`require-not-latest-init` (my pattern made `initContainers` effectively mandatory); fixed with the
`=(initContainers)` conditional anchor and re-proven. The deny-proof fired on exactly the intended
policies after the fix.

### Phase 1 exit criteria — met

- [x] `kubectl get ns` shows the five mission namespaces (+ bundle namespaces) with PSS restricted
- [x] Kyverno reports the baseline policies active (Ready=True, admission+background)
- [x] A sealed secret round-trips (cryptographically verified 4/4)
- [x] `kustomize build` clean on every tree (3 subtrees + phase root, 126 docs)
- [x] `kubectl apply --dry-run=client` equivalent-or-stronger: live apply succeeded on k3d-nagar
- [x] Docs updated in same change (`third_party/README.md`, ledger below)
- [x] No files outside the phase subtree + third_party + docs/ledger touched (I-9)

### Incidents (this phase)

- **k3s server container died mid-apply** (WSL2 cgroup flake: "unable to apply cgroup
  configuration: device or resource busy", ExitCode 128, not OOMKilled). `docker start` recovered
  it with state intact; cluster had nothing applied yet. Logged as **R7** (WSL2 flakiness); if it
  recurs before the WSL restart is approved, escalate.
- **CRD annotation limit:** kyverno's 2 large CRDs exceed 256 KB when kubectl client-apply
  duplicates them into `last-applied-configuration`; applied via **server-side apply**
  (`--force-conflicts`) — recorded for Phase 2+ (Argo uses SSA-compatible merge).

---

## Phase 2 — GitOps control plane (2026-09-29)

**Entry checklist (PHASES.md §2 Phase 2):** substrate healthy from Phase 1; Argo CD vendored
static (ADR-002); app-of-apps owns all phase trees.

### Deliverables (subtree: `deploy/phases/02-gitops/` + `deploy/third_party/argo-cd/`)

- **Vendored Argo CD v3.5.3** (tag-pinned static manifest from `raw.githubusercontent.com/
  argoproj/argo-cd/v3.5.3/manifests/install.yaml`, upstream sha256 recorded in
  `install-upstream.sha256`). Vendor-time filter (`filter.py`, documented in its docstring):
  removed the bundle Namespace doc and the dex + notifications Deployments (ADR-008 no-IdP,
  ADR-011 no-tracing/notifications) — 59→57 docs, no duplicates (verified by parse).
- **Digest pins (I-5):** `quay.io/argoproj/argocd@sha256:5a7367b1…`, `ghcr.io/dexidp/dex@sha256:
  f5f9fb37…`, `public.ecr.aws/docker/library/redis@sha256:e499175d…` (component `digest-pins/`).
- **Relocation to nagar-system:** namespace transformer + explicit CRB-subject rewrites
  (transformers do not touch RBAC subjects); pod-level securityContext + `part-of: nagarvault`
  + `nagar.io/phase` pod-template labels (Kyverno autogen evaluates pod templates) + minimal
  resources on all five workloads.
- **GitOps graph:** AppProject `nagar` (destinations limited to the six mission namespaces),
  root `nagar-mission-root` (auto-sync/selfHeal/prune/allowEmpty, ServerSideApply), children:
  `nagar-phase1-substrate` (ADOPTION of live Phase 1), `nagar-argocd-self` (self-managed,
  `ignoreDifferences` on argocd runtime secrets), forward-declared `nagar-phase3-object-cache`
  and `nagar-phase4-messaging` (empty placeholder kustomizations until their phases).
- **git-repo-mirror (ADR-014):** the cluster-reachable git transport (host daemon unreachable
  from the k3d network — probed). Bare repo staged into an image (registry staging model),
  served read-only by git-daemon (alpine `git-daemon` package — the base git package lacks the
  subcommand) as uid 1000 with owner-writable objects (`COPY --chown` + `chmod -R u+rwX`).
  Smoke-proven in-container and in-cluster (`git ls-remote` → HEAD). Immutable tags per cycle:
  phase2 → phase2-2 → … → phase2-5 (node image cache ignores re-pushed same tags — demonstrated
  why I-5 wants immutable references).
- **Kustomize build options:** Argo v3.5 removed `Application...buildOptions` (schema rejects)
  AND has no repo-server `--kustomize-build-options` flag (`Error: unknown flag`, observed live);
  the supported override is `argocd-cm: kustomize.buildOptions` — verified end-to-end inside the
  repo-server pod: bundled kustomize v5.8.1, phase-1 tree builds (126 docs) ONLY with the flag.

### Gate evidence

**G2.1 — adoption in place (zero churn):**

```
$ kubectl get pods … (cert-manager, kyverno, nagar-system) → agentic/tmp/pre-sync-uids.txt   # 8 pods
… Argo first sync of nagar-phase1-substrate (ServerSideApply; comparison succeeded, 69ms manifest gen) …
$ diff pre-sync-uids.txt post-sync-uids.txt
> nagar-system/argocd-* (6 lines: the NEW argo/mirror pods — expected)
ADOPTION-IN-PLACE-VERIFIED: every pre-existing pod UID byte-identical; zero recreation
$ kubectl get applications -n nagar-system
nagar-argocd-self           Synced   Healthy
nagar-mission-root          Synced   Healthy
nagar-phase1-substrate      Synced   Healthy
nagar-phase3-object-cache   Synced   Healthy
nagar-phase4-messaging      Synced   Healthy
```

**G2.2 — self-heal demonstrably reverts a manual mutation:**

```
$ kubectl scale deploy/cert-manager -n cert-manager --replicas=2
after-mutation replicas=2
$ watch loop (10s)
t+10s: replicas=2
t+20s: replicas=2
t+30s: replicas=1   ← argo self-heal restored git state
SELF-HEAL-VERIFIED at t+30s  (app: Synced/Healthy)
```

### Failures → fixes (all evidenced above)

1. Kyverno autogen rejected the first argo apply (missing `nagar.io/phase` on pod templates) —
   proof the policies gate even their own control plane; fixed in `argocd-patches.yaml`.
2. git-mirror CrashLoop #1: alpine `git` lacks the `daemon` subcommand → add `git-daemon` pkg.
3. git-mirror CrashLoop #2: upload-pack needs owner-writable object dirs for uid 1000 →
   `COPY --chown` + `chmod -R u+rwX`.
4. Tag-reuse trap: rollout restart picked the cached OLD `:phase2` image → immutable per-cycle
   tags (`phase2-N`) thereafter.
5. AppProject missing after the first partial bootstrap (`InvalidSpecError: referencing project
   nagar which does not exist`) → root.yaml re-applied; lesson: bootstrap is one SSA of the
   whole phase tree, partially-failed applies must be re-run as a unit.
6. Permanent OutOfSync on the 3 ClusterPolicies: the kyverno webhook server-side-defaults
   `emitWarning/admission/skipBackgroundRequests/allowExistingViolations`; declared the defaults
   in git (ce2fef91) rather than masking with ignoreDifferences. Also verified the `\ufffd` in
   console output was pipe-decoding, NOT file corruption (raw bytes are correct UTF-8 `§`).

### Phase 2 exit criteria — met

- [x] app-of-apps shows child Applications (5/5 Synced/Healthy at rev 5536f6fe)
- [x] a test change propagates via git push only (mirror cycles phase2-2…phase2-5 each landed
      via image refresh; live cluster otherwise untouched by hand)
- [x] self-heal reverts a manual mutation (~30 s — G2.2; the zero-maintenance proof)
- [x] Phase 1 substrate ADOPTED in place: zero pod churn (G2.1)
- [x] `kustomize build` clean across the phase trees; no files outside the phase subtree +
      third_party/argo-cd + docs ledger touched (I-9)
- [x] ADR-014 written (transport + Argo v3.5 settings facts); PHASES ledger flipped

---

## Phase 3 — Object store & cache (2026-09-29)

**Entry checklist (PHASES.md §2 Phase 3):** Phase 1 + Phase 2 complete (5/5 Applications Synced/Healthy
before the tree landed); `nagar-platform` exists at PSA `restricted`; Kyverno Enforce policies live;
internal-registry round-trip proven (G0.2: push `localhost:35000` → pull `k3d-nagar.localhost:5000`);
`nagar-minio-server` SealedSecret sealed offline against the in-cluster cert and round-trip verified (ADR-010).

### Deliverables (subtree: `deploy/phases/03-object-cache/`)

- **MinIO** StatefulSet (single node, ADR-006) + headless-style Service, `serviceName: minio`.
  Image is **source-built** (ADR-015)
  because every MinIO distribution channel is unreachable from this network; the `mc` client likewise.
- **Redis** StatefulSet (cluster-internal cache, no PVC — ARCHITECTURE §4.3: no persistence required).
- **`bucket-init` Job** — idempotent (`mc mb --ignore-existing`), creating the three frozen buckets from
  ARCHITECTURE §4.3 / MISSION.md §3: `raw-media`, `raw-sensitive-media`, `pg-backups` (the last is also
  CNPG's backup target, OPERATIONS §7). Matches the canonical exemplar `docs/manifests/exemplars/
  minio-statefulset.yaml`. (ARCHITECTURE §4.3's MinIO row listed only two buckets — corrected in this
  commit; the exemplar and MISSION.md §3 were always three.)
- **NetworkPolicies (SECURITY §8):** `default-deny`, `allow-dns-egress`, `allow-intra-namespace-egress`,
  `allow-minio-ingress`, `allow-redis-ingress`.
- **SealedSecret `nagar-minio-server`** in `nagar-platform` (keys `accessKey`, `secretKey`, `mcHostLocal`):
  sealed offline with `--cert`, applied, keys verified live, plaintext shredded (I-3). Nothing plaintext is
  tracked: `git ls-files deploy/phases/03-object-cache/secrets` → only `nagar-minio-server-sealed.yaml`.
- **Digest pins (I-5)** in `digest-pins/` (kustomize Component):

| image | pin |
|---|---|
| `mission/minio` | `sha256:d8464e6cc50064010cf17e1a1b74e4cf2fc0d9b23ab6bf0ff521bd2ea0af7576` |
| `mission/minio-mc` | `sha256:72e8defdcea3777f3935cb0f834294aa7b5bf210f85572939a363e65fda6326e` |
| `mission/redis` | `sha256:ca0acbb137c1dc3339c8b147a58fd6f42775d4599327b50e7b116c23de501af2` |
| `mission/busybox` | `sha256:66a6306db78bf2dbf3487f293aa8d6990d8e506fdffab9cc43fe422becf886e4` |

  Source-built provenance (ADR-015): server `RELEASE.2025-10-15T17-29-55Z` → binary sha256
  `36450819e0fa37907d2e8f225ef207f491e8f3a81cd3142e7f6370f0bb26e477`; `mc` `RELEASE.2025-08-13T08-35-41Z` →
  `e37fe3ed86cb4944d7d4bd0b1b8ac7fa3b74d54b5b5ce5acec870b8c2bef45bf`; both re-gated at image build by
  `ARG *_SHA256` + `sha256sum -c`.
- **Landed through GitOps only** (I-1): mirror cycles `phase3-1 … phase3-13`; the imperative calls were
  limited to the sanctioned transport step (build/push the mirror image + bump `newTag`, ADR-014) and the
  one `kubectl delete job` prescribed by OPERATIONS §9.3. No `kubectl edit`/`scale` of mission workloads.

### Gate evidence

**G3.1 — the three buckets exist (created by the GitOps Job, not by hand):**

```
$ kubectl logs -n nagar-platform -l job-name=bucket-init
Defaulted container "create-buckets" out of: create-buckets, wait-for-minio (init)
The cluster 'local' is ready
Bucket created successfully `local/raw-media`.
Bucket created successfully `local/raw-sensitive-media`.
Bucket created successfully `local/pg-backups`.
[2026-09-29 01:21:29 UTC]     0B pg-backups/
[2026-09-29 01:21:28 UTC]     0B raw-media/
[2026-09-29 01:21:29 UTC]     0B raw-sensitive-media/
buckets ready

$ kubectl exec -n nagar-platform minio-0 -- ls /data
pg-backups
raw-media
raw-sensitive-media          # same three, seen on the storage layer
```

**G3.2 — Redis answers ping:**

```
$ kubectl exec -n nagar-platform redis-0 -- redis-cli ping
PONG
$ … redis-cli info server | grep redis_version
redis_version:7.4.11
```

**G3.3 — PersistentVolumeClaims bound:**

```
$ kubectl get pvc -n nagar-platform
NAME           STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
data-minio-0   Bound    pvc-d296678f-93f3-4b23-8368-d9ddf30e7110   20Gi       RWO            local-path     108m
$ kubectl get pv | grep nagar
pvc-d296678f-…   20Gi   RWO   Delete   Bound   nagar-platform/data-minio-0   local-path
```

**G3.4 — GitOps convergence, zero churn where nothing changed:**

```
$ kubectl get applications -n nagar-system
nagar-argocd-self           Synced   Healthy
nagar-mission-root          Synced   Healthy
nagar-phase1-substrate      Synced   Healthy
nagar-phase3-object-cache   Synced   Healthy     ← rev f1e8f4d3
nagar-phase4-messaging      Synced   Healthy

$ kubectl get pods -n nagar-platform -o custom-columns=…
minio-0   Running   START 2026-09-29T01:37:56Z   k3d-nagar.localhost:5000/mission/minio@sha256:d8464e6c…
redis-0   Running   START 2026-09-29T00:39:53Z   k3d-nagar.localhost:5000/mission/redis@sha256:ca0acbb1…   ← untouched

$ docker stats --no-stream k3d-nagar-server-0
k3d-nagar-server-0   mem=2.318GiB / 7.608GiB
```

**I-2 (idempotency) and PVC safety, demonstrated, not asserted:** the mc image changed from tag to digest
pin, which re-created the Job (Force/Replace, ADR-016) and **re-ran it against a populated MinIO**:

```
$ kubectl logs -n nagar-platform -l job-name=bucket-init     # second run, same three buckets
Bucket created successfully `local/raw-media`.               ← `--ignore-existing`: no-op, no error
[2026-09-29 01:21:28 UTC]     0B raw-media/                  ← creation stamps still from run #1
buckets ready
```

The same cycle restarted `minio-0` (digest change) while the PVC kept the **same** PV
(`pvc-d296678f-…`) and `/data` still listed the three buckets — the charter's PVC-safety claim holds
across pod recreation; deleting the StatefulSet would likewise leave the PVC (k8s semantics).

### Convergence traps hit (→ ADR-016, OPERATIONS §12.13–12.14)

1. **Immutable Job template.** The `bucket-init` pod spec changed (the `mc` fix below). Argo cannot apply
   or diff a changed Job template — a dry run against the live Job returned
   `spec.template: Invalid value: … field is immutable` — and after the failed attempt the controller
   logged `Skipping auto-sync: comparing synced revisions … already attempted sync to [<rev>]`, i.e. the
   revision is not retried. Fix: declare `argocd.argoproj.io/sync-options: Force=true,Replace=true` **in
   git**. Observed over two further cycles: the Job is deleted+recreated exactly when its spec changes and
   is *not* re-run when it does not (no churn — I-2).
2. **A permanently OutOfSync StatefulSet starved the auto-sync.** `StatefulSet/minio` reported OutOfSync
   after every sync while every sibling was Synced. Cause: the API server defaults `apiVersion`, `kind` and
   `spec.volumeMode` inside `spec.volumeClaimTemplates`, and Argo's client-side differ does not normalize
   that subtree. Consequence (the part that actually blocked this phase): self-heal issued **partial**
   syncs — `Initialized new operation: … Resources:[]SyncOperationResource{{Group:apps,Kind:StatefulSet,
   Name:minio}}` — and each partial sync marked the revision "already attempted", so the pending Job fix
   could not land for a whole revision. Localization evidence: the `redis` StatefulSet omits the same class
   of pod-spec defaults and stays Synced (it has no `volumeClaimTemplates`).

   Diagnostic that isolated it (read-only, `kubectl diff` is a dry run):

   ```
   $ kubectl diff --server-side -f agentic/tmp/desired-minio-sts.yaml
   Error from server (Conflict): Apply failed with 1 conflict: conflict with "argocd-controller": .spec.volumeClaimTemplates
   $ kubectl diff --server-side --force-conflicts -f agentic/tmp/desired-minio-sts.yaml   # after declaring the fields
exit=0   # no value difference left
   ```

   Fix: declare the three fields in git (Phase-2 precedent: declare, never mask with `ignoreDifferences`).
   Related fact found while diagnosing: the pinned v3.5.3 controller binary does contain the `ServerSideDiff`
   sync option and `--server-side-diff*` flags; adopting server-side diff is deferred as an Argo
   control-plane (Phase-2 subtree) change — recorded in ADR-016 §4.

### Failures → fixes (in order; every one landed via its own mirror cycle)

1. `redis` image pulled from the wrong registry path + no explicit uid → local-registry rewrite and explicit
   `runAsUser` for redis/busybox (PSA `restricted` checks the *effective* uid; `aa8df12e`).
2. Duplicate `securityContext:` key in the Job pod spec (`yaml` keeps the last — silent authoring bug).
3. Init flow blocked by the egress policy: the first draft allowed DNS only, which is not the dependency —
   the Job talks to the MinIO **Service**; replaced with `allow-intra-namespace-egress` (`9cdb9c55`).
4. `mc` under `readOnlyRootFilesystem` could not write its config → `HOME=/tasks` +
   `MC_CONFIG_DIR=/tasks/.mc` on the writable volume (`a195c8c5`).
5. **The real bug:** `mc` derives the alias name from the `MC_HOST_<alias>` suffix *verbatim*, so
   `MC_HOST_LOCAL` registered alias `LOCAL` while the script called `local` — which then resolved to mc's
   built-in default `local → http://localhost:9000`, producing an endless
   `The cluster 'local' is unreachable: Get "http://localhost:9000/minio/health/cluster"`. Proven live in the
   failing pod (`mc alias list` showed `LOCAL … Src: env` **and** `local → http://localhost:9000` from
   config). Renamed to `MC_HOST_local` (`502e0f4e`).
6. Permanent `OutOfSync` on the StatefulSet (trap 2 above, `90c4fe32`) and the I-5 gap that the source-built
   images were tag-pinned rather than digest-pinned (`f1e8f4d3`).

### Invariants touched

- **I-1** — every workload change reached the cluster through the mirror/Argo path; imperative calls were the
  sanctioned transport step (ADR-014) plus the §9.3 Job deletion. **I-2** — proven by the Job re-run (above).
  **I-3** — only the sealed blob is tracked. **I-4** — probes/resources/NetworkPolicies on both workloads.
  **I-5** — all four images digest-pinned. **I-9** — `git diff --name-only 35cf977d..HEAD` touches only
  `deploy/phases/03-object-cache/**` plus the `deploy/phases/02-gitops/git-mirror/` transport tag (ADR-014)
  and the docs ledger.
- `kustomize build --load-restrictor LoadRestrictionsNone` → 11 docs, and
  `kubectl apply --dry-run=server` → every doc admitted by the **live** Kyverno policies.

### Open items / risks

- **R7 (memory + legacy stack).** The 15-container legacy Compose stack is no longer present in
  `docker ps -a` (it disappeared while Phase 3 was in progress; it was never stopped, restarted or deleted by
  this mission — consistent with ADR-013 §5). Headroom is comfortable: node container
  `2.318GiB / 7.608GiB`. The pending `~/.wslconfig` 14 GB restart remains an owner decision and is not
  required for Phase 3.
- **R8 (supply chain, new).** SECURITY §7's `syft` SBOM → `trivy` gate → `cosign sign` steps are not yet
  produced for *any* mission image, and for the two source-built images (ADR-015) upstream's image CVE
  pipeline is unavailable as a backstop. SECURITY §7 itself marks that CI as not-yet-built; the honest
  position is that digest pinning + the binary checksum gate are the only supply-chain controls in force so
  far. Proposed home: the Phase 9 hardening pass, where the scan/sign tooling can be vendored like the rest.

### Phase 3 exit criteria — met

- [x] buckets `raw-media` + `raw-sensitive-media` exist (plus `pg-backups`) — G3.1 (Job log + storage layer)
- [x] Redis passes ping — G3.2 (`PONG`, redis 7.4.11)
- [x] PVCs bound — G3.3 (`data-minio-0`, 20Gi, local-path)
- [x] `nagar-phase3-object-cache` Synced/Healthy at rev `f1e8f4d3`; the redis pod was not touched
- [x] `kustomize build` clean; server-side dry run admitted by live Kyverno; I-9 file scope respected
- [x] ADR-015 + ADR-016 written; PHASES ledger flipped; OPERATIONS §12.13–12.14 added

---

## Phase 4 — Messaging (2026-09-29)

**Entry checklist (PHASES.md §2 Phase 4):** substrate + GitOps + object/cache complete (all
Applications Synced/Healthy before this tree landed); `nagar-platform` at PSA `restricted`;
Kyverno Enforce policies live; internal-registry round-trip proven; Strimzi images staged by
digest and pullable in-cluster.

### Deliverables (subtree: `deploy/phases/04-messaging/` + vendored operator)

- **Strimzi Cluster Operator 1.2.0** vendored static (`deploy/third_party/strimzi/v1.2.0/`,
  upstream sha256 recorded) and relocated to `nagar-system` (control plane, beside Argo CD and the
  Sealed Secrets controller) with `STRIMZI_NAMESPACE=nagar-platform`.
- **Kafka KRaft single node** as two CRs — `Kafka/nagar` + `KafkaNodePool/dual-role` (ADR-006's
  single-node risk acceptance unchanged; the pool split makes widening a manifest edit, not a
  migration). Client listener on the frozen port **29092** (CONVENTIONS §4, I-6).
- **Idempotent topics Job** creating the six frozen topics (`--if-not-exists`), plus
  **`allow-kafka-ingress`** and **`allow-kafka-api-egress`** NetworkPolicies.
- **Digest pins (I-5)** for `mission/strimzi-operator` and `mission/strimzi-kafka`.
- **Neither CR declares the Entity Operator** — documented reason and one-line reversal path in
  `kafka.yaml`'s header.

### Gate evidence

**G4.1 — the six frozen topics exist and an event round-trips through the broker.** Run against
`kafka-bootstrap.nagar-platform.svc.cluster.local:29092` (the frozen DNS name from CONVENTIONS §3,
not the operator's generated one), from a client inside the image the manifests pin:

```
$ MSYS_NO_PATHCONV=1 kubectl exec -n nagar-platform nagar-dual-role-0 -- \
    /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka-bootstrap…:29092 --list
 ev.bus.telemetry.raw.v1
 health.camps.raw.v1
 nmc.complaints.dlq.v1
 nmc.complaints.raw.restricted.v1
 traffic.events.raw.v1
 water.sensors.raw.v1

$ echo '{"eventId":"p4-roundtrip-001","kind":"traffic.events.raw.v1","ts":"…"}' \
  | kubectl exec -i nagar-dual-role-0 -- …/kafka-console-producer.sh --topic traffic.events.raw.v1
PRODUCED
$ …/kafka-console-consumer.sh --topic traffic.events.raw.v1 --from-beginning --max-messages 1
{"eventId":"p4-roundtrip-001","kind":"traffic.events.raw.v1","ts":"…"}
Processed a total of 1 messages
```

The same job's own log is the second, independent witness for topic creation (it ran `create`
six times and then listed them back): `nagar-kafka-topics` → `Complete 1/1`.

**G4.2 — the broker is up and the Kafka CR is Ready:**

```
$ kubectl get kafka nagar -n nagar-platform
NAME    READY   WARNINGS   KAFKA VERSION   METADATA VERSION
nagar   True               4.2.0           4.2-IV1
$ … -o jsonpath='{.status.conditions[*].type} {.status.clusterId}'
Ready True · 4MHMqdk5QfKu4oGbwclETQ
$ kubectl get knp dual-role -n nagar-platform
NAME        DESIRED REPLICAS   ROLES                     NODEIDS
dual-role   1                  ["controller","broker"]   [0]
```

**G4.3 — GitOps convergence, all five Applications:**

```
$ kubectl get applications -n nagar-system
nagar-argocd-self           Synced   Healthy
nagar-mission-root          Synced   Healthy
nagar-phase1-substrate      Synced   Healthy
nagar-phase3-object-cache   Synced   Healthy
nagar-phase4-messaging      Synced   Healthy     ← rev 73e08b97
```

**G4.4 — the Kyverno carve-out did not weaken the general rule** (a PSS-compliant pod carrying no
mission labels is still denied, by *both* rules):

```
$ kubectl apply --dry-run=server -f compliant-unlabelled-pod.yaml
Error from server (Forbidden): … denied the request:
require-nagar-labels:
  check-part-of-label: '… rule check-part-of-label failed at path /metadata/labels/'
  check-phase-label:  '… rule check-phase-label failed at path /metadata/labels/'
```

**G4.5 — `kustomize build` clean (I-12) and admitted by live Kyverno:** phase-1 125 docs,
phase-2 64, phase-3 10, phase-4 31; `kubectl apply --dry-run=server` on the phase-4 build → every
document admitted.

**G4.6 — in-cluster digest pull (I-5), observed on the real pods:** kubelet's own events report
`Container image "k3d-nagar.localhost:5000/mission/strimzi-kafka@sha256:ef0f3302…" already present
on machine` for both the topics Job and the broker, i.e. the pinned digests resolve and run — not
just that they were pushed. (The pre-flight `crictl pull` recorded in
`digest-pins/kustomization.yaml` was performed when the images were staged; this entry is the
independent end-to-end witness.)

### Five convergence traps (each cost a deploy; all five are invisible to build/dry-run)

Phase 4's failures were qualitatively different from Phase 3's: every one of them was
**upstream-documented but unguessable**, and none could be caught by `kustomize build` or
`kubectl apply --dry-run=server`, because all five only manifest once the Cluster Operator
reconciles against a live API server. They are the argument for the "verify against official docs
and live behaviour, not memory" rule in MISSION.md §3.

1. **Node-pool adoption (empty cluster, no error in the manifest).** The operator refused the
   entire Kafka CR — `InvalidConfigurationException: No KafkaNodePools found for Kafka cluster
   nagar` — and created **no pods at all**. The pool is joined to the cluster by *two* fields that
   must both be present: `strimzi.io/node-pools: enabled` on the Kafka CR and
   `strimzi.io/cluster: nagar` on the pool. Symptom shape: a `Degraded` Application over an
   otherwise empty `Kafka` status.
2. **The operator owns the pod labels (a silent selector failure).** Strimzi hard-codes
   `app.kubernetes.io/*` on the pods it creates and drops `component` entirely (upstream: "cannot
   be overridden through template configuration"). Two consequences, one loud
   (`require-nagar-labels` denied the broker pod, because `part-of` is forced to `strimzi-nagar`)
   and one **silent**: `kafka-bootstrap`'s Service selector and the Kafka NetworkPolicy were both
   built on `component: broker`, so they selected **nothing** — a Service with no endpoints and a
   policy with no subject, both looking correct in git. Selectors now use Strimzi's own label set,
   copied from its generated `nagar-kafka-bootstrap`, and the pod templates no longer declare
   labels the operator will discard.
3. **The broker needs the Kubernetes API to start.** Strimzi 1.x loads the cluster CA / trust
   bundle through Kafka's `KubernetesSecretConfigProvider`, not a mounted volume, so the broker
   reads Secret `nagar-trustbundle` over the API server before it can boot. Phase 3's namespace
   `default-deny` blocked it and the pod CrashLoopBackOff'd on `java.net.ConnectException`.
   `allow-kafka-api-egress` was added, port-scoped rather than peer-scoped (a NetworkPolicy peer
   cannot name a k3s host process, and the ClusterIP-vs-post-DNAT address makes even an `ipBlock`
   guess a coin flip).
4. **The operator's admin client does not use the client port.** With the broker running and
   serving clients, every reconciliation still ended in `Error getting broker config:
   TimeoutException`, and the `Kafka` CR sat at `NotReady`. Strimzi 1.x runs three listeners
   (`PLAIN-29092`, `REPLICATION-9091`, `CONTROLPLANE-9090`); the operator's AdminClient uses
   **REPLICATION-9091**, which the ingress policy — written for the documented client port — did
   not allow. Confirmed by probing the operator pod instead of guessing:
   `BLOCKED 9090 · BLOCKED 9091 · OPEN 29092`. Ingress is now one rule per listener, with 9090
   restricted to broker pods.
5. **A vendored CRD that can never converge.** `kafkas.kafka.strimzi.io` was `OutOfSync` after
   every sync forever while its eleven siblings from the same file converged. `argocd app diff`
   rendered the entire drift as one line — `> properties: {}` — which identified it as the API
   server *pruning an empty schema node*, not human drift. Fixed by declaring the stored form with
   a JSON 6902 patch in this phase (ADR-016's declare-never-mask rule, applied to a CRD);
   `ignoreDifferences` was rejected because it would hide real schema drift on the one CRD most
   likely to move under a Strimzi upgrade. Diagnosis note: the first comparison script reported
   "no difference" because it skipped any key named `status`/`annotations` **at every depth** — and
   a CRD schema contains those as property names. The false negative is worth remembering.

Two process findings came out of this phase and are now written down rather than remembered:
**ADR-017** (the 1.2.0 contract: node-pool adoption, label ownership, API access, listener ports)
and **ADR-018** (advancing the git transport is an out-of-band operator step — the mirror is
circular by construction, since Argo reads the new tag *from* the pod whose tag git declares; the
cycle order is content → tag bump → payload → push → transport apply, recorded as §9.4).

### Honest correction to the Phase 3 record

Phase 3's entry claims the topics-style Job "is deleted+recreated exactly when its spec changes
and is *not* re-run when it does not (no churn — I-2)". This phase's evidence **contradicts that**:
`nagar-kafka-topics` was deleted and recreated on syncs where its spec had not changed (observed
across four consecutive syncs, each producing a fresh pod: `…-dk9fv → …-4sv5 → …-qw8rb → …-9gv8n`).
`Replace=true` is documented by Argo as delete-and-recreate, and so it does — on every sync. The
run itself is harmless (the Job is idempotent, `--if-not-exists`, ~4 s), so this is **reported as
drift in the record, not silently fixed**: the right remedy is to drop `Replace=true` and keep
`Force=true`, which requires a verification cycle of its own and is logged here as an open item.

### Invariants touched

- **I-1** — every workload change landed through the mirror/Argo path; the single out-of-band call
  per cycle is the transport step, now sanctioned and documented (ADR-018, §9.4). **I-2** — the
  topics Job re-runs idempotently against a populated broker without error; the `Replace` churn is
  recorded above. **I-3** — no plaintext secret added. **I-4** — both NetworkPolicies are explicit
  and least-privilege; resources/securityContext are declared on the pool; Strimzi's own PDB
  exists (`nagar-kafka`) and the pool's replica count is 1, so no PDB obligation attaches.
  **I-5** — both images digest-pinned, proven running. **I-6** — 29092 unchanged. **I-9** — scope
  below. **I-11** — no manifest resolves an upstream registry. **I-12** — all four trees build.
- **I-9 file scope** (`git diff --name-only b37644b9..HEAD`): `deploy/phases/04-messaging/**`, the
  vendored `deploy/third_party/strimzi/`, the `deploy/phases/02-gitops/git-mirror/` transport tag
  (ADR-014 practice), `docs/`, and **one Phase-1 file** — `deploy/phases/01-substrate/policies.yaml`
  (the scoped Strimzi carve-out, ADR-017 §4). That last one is a deliberate, documented
  cross-phase amendment, the same shape as the earlier declaration of the Kyverno webhook defaults
  (`ce2fef91`); the alternative was to weaken the label rule for every pod in the cluster.

### Open items / risks

- **R1 (memory) unchanged and comfortable:** the node container reports ~2.3–3 GiB of 7.6 GiB with
  MinIO, Redis, the broker, the operator and Argo running; the pending `~/.wslconfig` restart is
  still an owner decision and still not required.
- **R8 (supply chain) unchanged:** still no SBOM/scan/signature for any image; digest pinning plus
  the build-time checksum gate remain the only controls in force. Phase 9.
- **New, low severity — `Replace=true` churn on Jobs** (see the correction above).
- **New, low severity — `allow-kafka-api-egress` is port-scoped, not peer-scoped.** It is the one
  deliberately imprecise rule in the namespace; ADR-017 §5 records the exact reasoning and the
  upgrade path (control-plane `ipBlock`) for Phase 9.
- **Structural, deferred to Phase 9/10 — the git transport is inside the tree it serves**
  (ADR-018). The step is sanctioned and scripted; the cleanup is not done.

### Phase 4 exit criteria — met

- [x] Kafka CR `Ready True`, Kafka 4.2.0 / metadata 4.2-IV1 — G4.2
- [x] The six frozen topics exist (ARCHITECTURE §4.2) and an event round-trips — G4.1
- [x] DLQ topic present (`nmc.complaints.dlq.v1`) — G4.1
- [x] `nagar-phase4-messaging` Synced/Healthy at rev `73e08b97`; all five Applications Synced — G4.3
- [x] `kustomize build` clean on every tree; live Kyverno admits every document — G4.5
- [x] Label policy still denies unlabelled pods after the carve-out — G4.4 (negative proof)
- [x] Both images digest-pinned and observed running — G4.6 (I-5)
- [x] ADR-017 + ADR-018 written; PHASES ledger flipped; OPERATIONS §9.4 + §12.15–12.19 added

---

## Phase 5 — Relational store (2026-09-29)

**Entry checklist (PHASES.md §2 Phase 5):** Phases 1–4 complete (all Applications Synced/Healthy
before the tree landed); `nagar-postgres-app` SealedSecret present from Phase 1; `pg-backups`
bucket present from Phase 3 (hard prerequisite since Barman Cloud 3.16 no longer creates buckets —
ADR-019 §2); internal-registry round-trip proven (G0.2).

### Deliverables (subtree: `deploy/phases/05-postgres/` + vendored `deploy/third_party/cnpg/`)

- **CloudNativePG 1.30.1 controller** vendored static (`deploy/third_party/cnpg/v1.30.1/`,
  upstream sha256 recorded), kept in its upstream-native `cnpg-system` namespace (ADR-019 §3),
  PSS-labelled by patch. Controller is PSS-restricted-compliant as shipped (uid 10001, drop ALL,
  RO rootfs) — nothing patched, documented why.
- **`Cluster/postgres`** — 2 instances, PostgreSQL **15.17** (`15.17-system-trixie` line of the
  CNPG image, chosen because the legacy stack pinned `postgres:15-alpine` and the exemplar says
  "postgres:15 line" — ADR-019 §1), `nagardb` owned by `nagar`, native `barmanObjectStore` backups
  to `s3://pg-backups/` with gzip WAL+data and a 14-day retention window, `prefer-standby` backup
  target, `inheritedMetadata` carrying the mission labels onto operator-created pods.
- **`001_create_tables.sql`** — authored fresh (ADR-019 §9): `users`/`sessions`/`audit_logs` + the
  five department tables, every statement `IF NOT EXISTS`-equivalent, PII columns named exactly as
  the queryService denylist expects, `source_system + source_record_id` unique per table as the
  §3.2 duplicate key, officer roles as NOLOGIN roles with SELECT-only grants (SECURITY §3.3 "second
  wall"), `nagar` a member of both officer roles for Phase-7b `SET ROLE`.
- **Migration Job** on the operator-managed superuser (ADR-019 §6), gated by a
  `wait-for-postgres` init container, SQL delivered via a hash-suffixed kustomize ConfigMap.
- **`ScheduledBackup/postgres-daily`** — `0 0 3 * * *` + `immediate: true` (create-time trigger,
  not per-sync).
- **Restore drill** (`restore-drill/`, ADR-020) — buildable, deliberately unreconciled: canary
  Job → on-demand Backup → scratch `Cluster` recovering via `externalClusters` + `bootstrap.recovery`
  → verify Job that connects **as `nagar` with the sealed app password** and asserts tables,
  canary, and the grant matrix.
- **NetworkPolicies** — `allow-postgres-ingress` (5432 from namespace + nagar-app; **8000 from
  cnpg-system**, the operator→instance channel upstream documents), `allow-postgres-api-egress`
  (ports 443/6443, port-scoped, the ADR-017 §4 precedent).
- **SealedSecret `nagar-postgres-bootstrap`** — `kubernetes.io/basic-auth` with
  `username=nagar` and **the password Phase 1 already sealed into the app tier's `databaseUrl`**
  (ADR-019 §5): read from the live unsealed Secret, re-sealed offline with `--cert`, plaintext
  never printed, shredded after sealing. `bootstrap.initdb.secret` then pins it.
- **Digest pins (I-5):** `mission/cnpg-operator` `sha256:b0f9805b…`; `mission/cnpg-postgresql`
  `sha256:0e1a5a4e…` (registry-read-back; differs from the upstream index digest
  `dfe703aa…` — G0.3 note 3). One operand image serves cluster + client Jobs (uid 26 + `fsGroup`
  on a tmp emptyDir HOME); the exemplar's separate `postgres:15-alpine` client image was
  dropped.

### Gate evidence

**G5.1 — cluster healthy, migration applied and idempotent:**

```
$ kubectl get cluster postgres -n nagar-platform
NAME   AGE  INSTANCESTATUS  ...
→ `kubectl get cluster postgres` → phase "Cluster in healthy state"
$ kubectl get pods -n nagar-platform | grep postgres
postgres-1  1/1 Running  0
postgres-2  1/1 Running  0
$ kubectl get jobs -n nagar-platform → nagar-db-migrate Complete 1/1 (56s)
job log tail: 8×ALTER TABLE · 5×GRANT · GRANT ROLE ×2 · migrations complete
$ # idempotency: full re-apply of 001_create_tables.sql with ON_ERROR_STOP=1
→ 0 errors; row counts unchanged (users=0, nmc_complaints=0, audit_logs=0)
$ # all eight tables listed via \dt as nagar
```

**G5.2 — `SELECT 1` via `postgres-rw` as the application role, with the Phase-1 password:**

```
$ PW=$(kubectl -n nagar-platform get secret nagar-postgres-bootstrap -o jsonpath='{.data.password}' | base64 -d)
$ kubectl exec -n nagar-platform postgres-1 -- env PGPASSWORD=$PW psql \
    -h postgres-rw.nagar-platform.svc.cluster.local -U nagar -d nagardb -tAc \
    "SELECT 'AUTH-OK', current_user, current_database();"
AUTH-OK|nagar|nagardb
```

This is the credential contract proven end-to-end: the password sealed in Phase 1 for the app
tier authenticates the role that owns `nagardb`.

**G5.3 — grant matrix (SECURITY §3.3) enforced in the database:**

```
SELECT 'nmc->health:'||has_table_privilege('nmc_officer','health_camp_records','SELECT')...
→ nmc->health:false  health->health:true  nmc->complaints:true
```

**G5.4 — backup completed into MinIO:**

```
$ kubectl get backup -n nagar-platform
postgres-daily-20260929101401  postgres  barmanObjectStore  completed
$ MSYS_NO_PATHCONV=1 kubectl exec -n nagar-platform minio-0 -- sh -c \
    'ls /data/pg-backups/postgres/; ls /data/pg-backups/postgres/base'
base  wals
20260929T102802        ← WAL archive `wals/0000000100000000` present alongside
```

**G5.5 — restore drill (ADR-020, applied+deleted per §9.5):**

```
$ kustomize build …/restore-drill | kubectl apply -f -   (5 docs)
→ canary=Complete · backup pg-drill-backup=completed ·
  cluster postgres-restore-drill="Cluster in healthy state"
$ kubectl logs job/pg-drill-verify   (final state)
--- restored tables --- 8/8 present (nmc_complaints rows=1)
--- canary --- canary rows=1 (written before the backup, read after the restore)
--- officer role matrix --- nmc_officer→health=f · health_officer→health=t
RESTORE-DRILL-VERIFIED
$ kustomize build …/restore-drill | kubectl delete -f -  → "drill fully removed"
```

**G5.6 — GitOps convergence, all six Applications:**

```
nagar-argocd-self           Synced  Healthy
nagar-mission-root          Synced  Healthy
nagar-phase1-substrate      Synced  Healthy   ← re-healthy after the 12.23 repair
nagar-phase3-object-cache   Synced  Healthy
nagar-phase4-messaging      Synced  Healthy
nagar-phase5-postgres       Synced  Healthy   ← rev e82f268d
```

Trees build clean (I-12): phase-1 125 docs, phase-2 64, phase-3 10, phase-4 31, phase-5 32
(+5 unreconciled drill docs); no unpinned image reference anywhere in the phase-5 build.

### Failures → fixes (each its own mirror cycle; none visible to build/dry-run alone)

1. **The new Application file was never registered in `apps/kustomization.yaml`.**
   `kustomize build` rendered 4 Applications, Argo synced the root, and phase 5 simply didn't
   exist. The "adding a phase = adding a file" comment was half right — the file must also be
   listed. `phase5-2` (combined with fix 2 below).
2. **`namespace cnpg-system is not permitted in project 'nagar'`** — the AppProject destination
   whitelist didn't know the CNPG namespace. Worse, `root.yaml` (where the fix lives) is part of
   the phase-2 bootstrap tree but of **no Application's path**: `argocd-self` watches only
   `deploy/phases/02-gitops/argocd`, the root only `.../apps`. The retry loop kept failing against
   a stale live AppProject. Fix: extend `root.yaml` (`phase5-3`) **and** replay the phase-2
   bootstrap tree once with SSA — sanctioned as §9.4 byte-identity, plus §12.20/§12.23 rows.
3. **CNPG's own webhook denied the Cluster twice** (webhook-only, invisible to `--dry-run=client`):
   `spec.imageName: Can't use just the image sha as we can't detect upgrades` — the operator parses
   the tag; the pin is now `:15.17-system-trixie@sha256:0e1a5a4e…` — and
   `Memory request is lower than PostgreSQL shared_buffers` — request raised to 1Gi (= limit).
   `phase5-4`. The dry-run *server* output also surfaced upstream's warning that native Barman
   Cloud support is removed in 1.31.0 — the ADR-019 §2 migration trigger is now concrete.
4. **The drill's verify Job raced the recovery** (first run FailureTarget: it started while WAL
   replay was still running and burned its backoffLimit before `-rw` had endpoints; the re-run
   after the cluster went healthy passed, proving the checks correct and the ordering wrong).
   Added the same wait-init the migration Job has, pointed at the drill cluster.
5. **The cert-manager outage (the big one).** Mid-Phase-5, `nagar-phase1-substrate` flipped to
   Progressing: cert-manager had **zero pods**, every ReplicaSet event
   `admission webhook "validate.kyverno.svc-fail" denied … check-part-of-label, check-phase-label`.
   Root cause was **not** in Phase 5: `cert-manager-patches.yaml` (Phase 1) never added the
   mission pod-template labels — only Namespace labels and resources. The first pods predated the
   live Kyverno webhook and kept running; Argo saw no drift because git itself lacked the labels;
   the Docker-VM restart (Day-0 infrastructure flake, R7) forced pod re-creation against the
   now-live policy. TwoPhase-4-class lessons compounded: a policy that only ever evaluated
   pre-existing pods proves nothing (the negative test must create a pod), and a patch that labels
   the Namespace does not label the pods. Fixed in the phase-1 subtree (`phase5-5`), replayed with
   SSA (byte-identity), documented as §12.23; phase 1 converged on the new revision and all six
   Applications are green. The `kubectl get pods -A` count after recovery: 24 pods, node at
   3.5 GiB / 13.65 GiB.

### Honest corrections to the record

- The Phase-4-era claim that the WSL memory raise "remains an owner decision and is not required"
  is overtaken by events: the raise took effect (node now 13.65 GiB), which is what made the
  restore drill's third PostgreSQL instance comfortable. R1 is **downgraded**.
- `deploy/third_party/README.md` had drifted from reality — the Phase-4 vendoring added Strimzi
  but not its row, and Phase 5 initially repeated the mistake with the digest-pins table
  (listed 3 images; consolidating to 2 made it wrong differently). Both fixed in this phase; the
  table now records the per-phase pin components and the source-URL checksum convention.
- The mirror tag `phase5-1` was built and pushed before the app-of-apps registration fix — it
  exists in the registry but was never read by Argo (dead tag, per ADR-018 §3 the name is not
  reused).

### Invariants touched

- **I-1** — workload changes through mirror/Argo only; out-of-band calls were the sanctioned
  transport step (§9.4) and the phase-2 bootstrap replay when the project gate wedged. **I-2** —
  migration re-applied cleanly; drill canary idempotent. **I-3** — only sealed blobs tracked; the
  bootstrap password was sealed from the live secret and the plaintext shredded. **I-4** —
  policies/NetworkPolicies/resources as documented. **I-5** — two images, both digest-pinned
  (tag+digest for the operand, per CNPG's own validation). **I-6** — 5432 unchanged; `nagardb`,
  `postgres-rw`, `pg-backups` all registry names. **I-7/I-8** — no new alert; ADR-019/ADR-020
  written. **I-9** — scope below. **I-11** — no manifest resolves an upstream registry. **I-12** —
  all trees build.
- **I-9 file scope** (`git diff --name-only 2065f8eb..HEAD`, excluding the sanctioned transport
  tag): `deploy/phases/05-postgres/**`, vendored `deploy/third_party/cnpg/`, **two Phase-1/2
  files**: `deploy/phases/02-gitops/root.yaml` (AppProject destination) and
  `deploy/phases/01-substrate/cert-manager/cert-manager-patches.yaml` (12.23 repair). Both are
  deliberate, documented cross-phase amendments of latent defects, the established pattern
  (Phase 4's `policies.yaml` carve-out, Phase 2's webhook-defaults declaration).

### Open items / risks

- **R8 (supply chain) unchanged:** no SBOM/scan/sign for any image yet; Phase 9.
- **`Replace=true` churn on init Jobs** unchanged from Phase 4 (applies to the migration Job too).
- **The two `git ls-files`-visible sealed secrets now differ in shape**: phase-5's bootstrap blob
  carries a `kubernetes.io/basic-auth` template; Phase 1's three are `Opaque`-shaped with labels
  only. Cosmetic drift only, no action needed.
- **Native Barman Cloud removal in CNPG 1.31.0** is now upstream-confirmed (deprecation warning
  observed live). ADR-019 §2's trigger stands: migrate to the Barman Cloud plugin at the 1.31
  upgrade.

### Phase 5 exit criteria — met

- [x] `001_create_tables.sql` applied (and idempotent) — G5.1
- [x] `SELECT 1` via `postgres-rw` — G5.2, as the application role with the Phase-1 password
- [x] A backup completed — G5.4 (immediate ScheduledBackup, `completed`, base+`wals/` in MinIO)
- [x] A restore drill into a scratch cluster succeeded — G5.5 (`RESTORE-DRILL-VERIFIED`, then
      `kubectl delete` per §9.5)
- [x] `kustomize build` clean on every tree; no unpinned image — G5.6
- [x] All six Applications Synced/Healthy — G5.6
- [x] ADR-019 + ADR-020 written; PHASES ledger flipped; OPERATIONS §7/§9.5/§12.20–12.23 added;
      ARCHITECTURE §3.3 schema path corrected; `third_party/README.md` registry completed

---

## Phase 6 — Vector & LLM tier (2026-09-29)

**Scope:** `deploy/phases/06-vector-llm/` + app-of-apps registration. Mirrors `phase6-1` →
`phase6-5`; Argo Application `nagar-phase6-vector-llm` Synced/Healthy. No pushes to any remote.

### G6.1 — Environment re-verified

- `docker 29.8.1`; `k3d cluster list` → `nagar 1/1` (server + LB + registry up 7h+). LB port
  re-checked after the Docker restart trap: `6443/tcp -> 0.0.0.0:57306`.
- Session lesson recorded: `k3d kubeconfig write` takes the **cluster name** (`nagar`), not the
  `k3d-nagar` context alias; the written kubeconfig is at `%TEMP%/kubeconfig`.
- Baseline before the phase: 6/6 Applications Synced/Healthy; node 13.65 GiB.

### G6.2 — Model gate (`MODEL-JOB-OK`, live)

Models staged host-side (R3 flake worked around with persistent short-retry pulls), only the two
mission models shipped — the host's unrelated 9.6 GB gemma4 excluded:

| model | size | digest (ollama) |
|---|---|---|
| `bge-m3` | 1.2 GB | `790764642607…` |
| `qwen3:1.7b` | 1.4 GB | `8f68893c685c…` |

Payload `mission/ollama-models:phase6-1` (8 blobs, 2.52 GB), build-time `sha256sum -c` gate
against `models/models-manifest.sha256` (committed). In-cluster Job re-verified the checksums,
restored into the `ollama-models` PVC, then probed `http://ollama:11434/api/tags` with busybox
wget (the payload image has no ollama binary — `ollama list` was never an option inside the Job):
`MODEL-JOB-OK`, server lists both models. ADR-021 records the shared-PVC provisioning decision.

### G6.3 — Qdrant up (three-part fix, each proven before landing)

1. **Env override ineffective.** `QDRANT__STORAGE__STORAGE_DIR` did not take effect in 1.15.1;
   pod panicked on `./storage` vs the read-only root. Fixed via `workingDir: /qdrant` so the
   upstream relative defaults land on the PVC (landed `phase6-3`, previous turn).
2. **Snapshots path.** Still fatal: `Panic occurred in file src/actix/mod.rs at line 73 …
   Failed to create snapshots temp directory at ./snapshots/tmp: ReadOnlyFilesystem` (upstream
   also defaults `snapshots_path: ./snapshots`). **Verified on the host first** with the exact
   pinned digest, `--read-only`, uid 1000, and a writable `./snapshots`: qdrant serves, `/healthz`
   200, `/readyz` "all shards are ready"; the `Failed to create init file indicator` WARN and the
   `Filesystem check failed` ERROR are both non-fatal by the same run. Fix: `snapshots` emptyDir
   at `/qdrant/snapshots` (`phase6-4`) — snapshots of a rebuildable cache need no PVC.
3. **Rollout deadlock.** After `phase6-4` the STS template was correct but the pod stayed on the
   old revision: with `replicas: 1`, the crash-looping ordinal-0 pod blocks its own replacement
   (rolling update waits for N-1…0 Ready before touching N). Deleted the dead pod once —
   controller recreated it from `updateRevision` immediately (§9.3 class); qdrant-0 Ready,
   endpoints populated. Recorded as §12.24.

### G6.4 — Index Job (`INDEX-SYNC-OK`, live)

Connectivity restored, the Job then failed with `400 … value -8967166598452498473 is not a valid
point ID, valid values are either an unsigned integer or a UUID`. Reproduced from the indexer
Deployment pod with the Job's exact batch (40/40 embedded, dim 1024) to capture the error body:
the signed sha256 fold produced negative ids. Fix: unsigned u64 fold (`phase6-5`), digest
re-pinned from the registry header and **machine-compared** against the pin file (`PIN-MATCHES-
REGISTRY`) after two manual transcription slips earlier in the session — never retype a digest.

```
[indexer] loaded 40 schema documents
[indexer] embedded 40 documents (dim=1024)
[indexer] collection 'nagar_schema' exists with dim=1024 — keeping it (idempotent re-run)
[indexer] upserted 40 points; collection now reports points_count=40
SUMMARY documents=40 upserted=40 points_count=40 dim=1024
INDEX-SYNC-OK
```

Job `succeeded=1`. A leftover probe point (id 1, "probe") from the diagnosis was removed by
dropping and letting the Job rebuild the collection — the 40/40 count above is post-rebuild.

### G6.5 — Retrieval round-trip (`RETRIEVAL-ROUNDTRIP-OK`, live)

Query `which table stores citizen complaint records and their status?` → bge-m3 embed (dim 1024)
→ qdrant search, top hits:

```
GATE count: status=green points_count=40 dim=1024 distance=Cosine
GATE embed: model=bge-m3 dim=1024
GATE hit: score=0.6736 doc_id=table-nmc_complaints-01 table=nmc_complaints
GATE hit: score=0.5661 doc_id=overview-01
GATE hit: score=0.5340 doc_id=table-nmc_complaints-03
RETRIEVAL-ROUNDTRIP-OK
```

The top hit is the correct table doc — retrieval quality, not just plumbing, is evidenced.

### G6.6 — Idempotent `/reindex` + platform gates

- `POST /reindex` twice from the indexer Deployment: `{"status":"ok","documents":40,
  "upserted":40,"points_count":40,"dim":1024}` both times; `points_count` 40 after each —
  deterministic ids make re-runs no-ops. Charter exit criterion met.
- Applications: **7/7 Synced/Healthy** (`nagar-argocd-self`, `nagar-mission-root`, phases 1,
  3, 4, 5, 6).
- `kustomize build` all six phase trees (LoadRestrictionsNone — the vendored third_party refs are
  intentional air-gap staging; the default restrictor blocks only those): **all OK**.
- Node: `8.073 GiB / 13.65 GiB (59%)` after phase 6; disk 392G free; no MemoryPressure.
- NetworkPolicies present: `default-deny`, `allow-dns-egress`, `allow-ollama-ingress`,
  `allow-qdrant-ingress`, `allow-schema-indexer-ingress`, intra-namespace egress (+ phases 1–5 set).

### Corrections / lessons this phase

- The app-of-apps registration lesson (§12.20 tail) was **hit a second time** (phase 6 Application
  existed as a file but shipped nothing until registered). The rule is now self-enforcing: the
  registration is part of the same commit as the Application file.
- Digest handling tightened after two retyping slips: digest pins are now verified by string-
  comparing the pin file against the registry's `Docker-Content-Digest` header, never by eye.
- The `qdrant-probe` debug pod was correctly rejected by PSA restricted — diagnosis ran via
  `kubectl exec` into the existing indexer Deployment instead (no privileged pod, no exceptions).

### Invariants touched

**I-1** — all workload changes through mirror/Argo; out-of-band ops: §9.4 transport advances
(×3) and the single §9.3 pod deletion. **I-2** — Job re-verify+restore, unsigned-id upserts,
`/reindex` ×2 no-op. **I-3** — no secrets in the phase (none needed). **I-4** — probes/resources/
NetworkPolicies/PDB-equivalent single-replica note on all new workloads (Kyverno-enforced).
**I-5** — 5 images, all registry-header digests, pinned `tag@sha256` where operand webhooks matter.
**I-6** — 6333/6334/11434/4005 unchanged. **I-7** — no new alert (Phase 9). **I-8** — ADR-021
written; earlier manifest references now resolve. **I-9** — scope: `deploy/phases/06-vector-llm/**`,
`deploy/phases/02-gitops/apps/` (new Application + registration), mirror tag, docs.
**I-11** — no manifest references an upstream registry. **I-12** — all trees build.

### Phase 6 exit criteria — met

- [x] `ollama list` equivalent shows both models (MODEL-JOB-OK; `/api/tags` listed bge-m3 +
      qwen3:1.7b) — G6.2
- [x] Qdrant `nagar_schema` holds exactly 40 vectors — G6.4/G6.5 (count via qdrant API)
- [x] `/reindex` idempotent re-run works — G6.6 (twice, 40/40 stable)
- [x] All Applications Synced/Healthy; every tree builds; resources re-checked — G6.6
- [x] ADR-021 written; PHASES ledger flipped; OPERATIONS §12.24/12.25 added

---

## Phase 7a — authService (2026-09-30)

**Scope:** `deploy/phases/07-app-auth/` (fresh code per ADR-013; the legacy top-level
`authService/` path stays deleted until Phase 10 rules on final layout) + app-of-apps
registration. Mirrors `phase7a-1`, `phase7a-2`; Application `nagar-phase7a-auth` Synced/Healthy.
No pushes to any remote.

### G7a.1 — Environment re-verified

docker 29.8.1; `k3d cluster list` → nagar 1/1; LB `6443->57306`; 7/7 Applications green at
start; node 5.5/13.65 GiB, disk 396G. Live-state contract checks before writing code:
`nagar-app` already in AppProject destinations (no §12.20 gate); `nagar-jwt` key `jwtSecret`
and `nagar-postgres-app` key `databaseUrl` exist from Phase 1 (SECURITY §6.2 key map — the
exemplar's `$(PGPASSWORD)` interpolation predates the live secret shape; no new SealedSecret);
CNPG owner `nagar`; `allow-postgres-ingress` already admits nagar-app→5432; `postgres-rw`
selector `cnpg.io/cluster=postgres, instanceRole=primary`.

### G7a.2 — TDD: 22 hermetic tests, red → green

Tests written first (`auth/tests/test_auth.py`), watched fail (`ModuleNotFoundError: app`),
then implemented. Final: **22 passed, 1 warning in 1.64s**. Coverage: JWT claim set incl.
`exp-iat == 3600` and aud/iss validation; cookie flags (httponly/samesite=lax/secure per env);
wrong-password 401; unknown-user 401 (timing-equalized against a dummy argon2 hash — no user
enumeration); admin gate on /create (401/403); unknown role 422; duplicate username 409;
logout denylist → /whoami 401; rate limit 429 on 6th attempt; seed idempotency. The suite
caught a real contract subtlety: logout must consult token validity but NOT the revocation
list (a revoked-token replay logout stays 200 — idempotent), while /whoami must 401 on the
same token. Implementation split `claims_from_request` (no denylist) from
`identity_from_request` (denylist) accordingly.

### G7a.3 — Image + pin

`mission/nagar-auth-service:phase7a-1` built on the host from the phase subtree
(python:3.12-slim; uid 1000; test files NOT shipped). Registry header digest
`sha256:adf0ff3c3154a605c71cf4f5931cce611668e6fbb10d84deedabc9cab820832a` → pinned in
`digest-pins/` component → **machine-verified `PIN-MATCHES-REGISTRY`** (string equality vs
`Docker-Content-Digest`, per the Phase-6 lesson).

### G7a.4 — Landing

Commit `949bf6ee` carries code + manifests + Application `nagar-phase7a-auth` AND its
`apps/kustomization.yaml` registration in one commit (the twice-bitten Phase-5/6 lesson).
Mirror cycle `phase7a-1` (§9.4); Argo created the app and synced; **8/8 Applications
Synced/Healthy**; both replicas 1/1 Running with `/dbcheck` readiness proving DB reachability
through the NetworkPolicy before any E2E.

### G7a.5 — Fix under fire: writable /tmp

The in-pod E2E transfer failed with `cannot create /tmp/pw: Read-only file system` — the
hardened `readOnlyRootFilesystem: true` (correctly) leaves no scratch. Added an `emptyDir` at
`/tmp` (nothing durable is written at runtime), landed as `phase7a-2`; rollout zero-downtime
(maxUnavailable 0); `TMP-OK` probe on the new ReplicaSet.

### G7a.6 — Seeded admin + cluster-internal E2E (`E2E-AUTH-OK`, 17/17 PASS)

Seed per OPERATIONS §5 (`seed_admin.py --username admin --user-id admin-001`, §9.1; password
28 chars, captured ephemerally, never logged, shredded with the E2E files — pod and host).
Seed idempotency proven live afterwards: `user 'admin' already exists — no-op`.
E2E ran from inside pod `auth-service-68669cb78c-22hb7` with stdlib-only urllib (the runtime
image deliberately has no test deps), against the **Service** URL for contract paths and a
direct pod IP for the per-IP limiter:

```
PASS liveness GET / -> 200          PASS dbcheck SELECT 1 -> 200
PASS whoami without token -> 401    PASS login wrong password -> 401
PASS login seeded admin -> 200      PASS Set-Cookie httponly / samesite=lax / not secure
PASS whoami echoes admin identity   {"sub":"admin-001","role":"admin","jti":"744da7e3…"}
PASS POST /create as admin -> 200   {"username":"officer7a","role":"nmc_officer"}
PASS new officer can login -> 200   PASS POST /create as officer -> 403
PASS officer whoami role echo       PASS 6th login within a minute -> 429 (5 req/min/IP)
PASS bearer token valid pre-logout -> 200
PASS logout -> 200
PASS same token after logout -> 401 (jti denylist)
E2E-AUTH-OK
```

DB evidence (primary pod, no secrets printed): `users` = admin(admin) + officer7a(nmc_officer),
both `$argon2id$…`, **0 rows with non-argon2id hash**; `sessions` = `744da7e3…` `revoked = t`
(the E2E logout), officer session live. Duplicate-row guards before each re-seed attempt kept
the ritual idempotent (`DELETE 1` of mission-created test users only).

### G7a.7 — Parity + platform gates

Exemplar parity vs `docs/manifests/exemplars/auth-service-deployment.yaml` — all 11 probed
shapes present (replicas 2, maxUnavailable 0, PDB minAvailable 1, :4000, /dbcheck + / probes,
no SA token automount, 128Mi/256Mi, phase "07", readOnlyRootFilesystem). Documented deviations
(live-state corrections, in manifest headers): `databaseUrl` secretKeyRef; `COOKIE_SECURE=false`
until Phase 8 TLS; pod-template mission labels (§12.23); writable /tmp emptyDir.
`kustomize build` — **all 7 phase trees OK** (LoadRestrictionsNone, vendored third_party refs).
Node after 7a: 6.45/13.65 GiB (47%), disk 388G, no pressure conditions.

### Session lessons (host quirks, not platform issues)

MSYS path conversion struck in three new flavors this phase: (1) a bare pod-absolute argument
(`/tmp/e2e7a.py`) is rewritten to a host path — wrap the remote invocation in `sh -c '…'`;
(2) `export KUBECONFIG=x MSYS_NO_PATHCONV=1` in one statement disables conversion of the
KUBECONFIG value itself, breaking kubectl — set them as separate statements; (3) dict-based
header access is case-sensitive where `resp.headers` iteration is not (E2E harness bug, fixed
same-run). Secret material was never exposed by any of these failures (cleanup ran
unconditionally; affected seeds were deleted and re-performed).

### Invariants touched

**I-1** — workload changes via mirror/Argo only; out-of-band: §9.4 advances ×2, §9.1 seed,
and `DELETE` of two mission-created E2E test users (data cleanup of my own artifacts, idempotent
re-seed after). **I-2** — seed re-run no-op; /create duplicate 409; JWTs verified against live
env per request. **I-3** — password printed once to the operator's ephemeral capture only;
DB stores argon2id hashes (0 plaintext rows verified); no secrets in git. **I-4** — probes,
resources, PDB, NetworkPolicy, non-root read-only container. **I-5** — image digest pinned from
the registry header, machine-verified. **I-6** — 4000 unchanged. **I-7** — none (Phase 9).
**I-8** — no new ADR: every deviation is a live-state reconciliation of ADR-013/SECURITY §6.2/
§12.23, documented in manifest headers and here. **I-9** — scope: `deploy/phases/07-app-auth/**`
+ the two app-of-apps files + mirror tag + docs. **I-11** — base manifest references
registry.nagar.internal:5000 only. **I-12** — all trees build.

### Phase 7a exit criteria — met

- [x] Seeded admin user — G7a.6 (OPERATIONS §5 ritual, idempotency proven)
- [x] `/login` E2E via cluster-internal curl — G7a.6 (17/17 PASS, `E2E-AUTH-OK`)
- [x] Exemplar parity check — G7a.7 (11/11 shapes, deviations documented)
- [x] 8/8 Applications Synced/Healthy; all trees build; resources re-checked — G7a.7

---

## Phase 7b — queryService (2026-09-30)

**Scope:** `deploy/phases/07-app-query/` (fresh code per ADR-013) + app-of-apps registration.
Mirror `phase7b-1`; Application `nagar-phase7b-query` Synced/Healthy. No pushes to any remote.

### G7b.1 — Contracts read before code

`POST /query` (JWT + role RBAC) from ARCHITECTURE §4.1; guardrails from §3.4 (SELECT-only
sqlglot AST, per-role table RBAC, PII denylist `name, phone, email, address, aadhaar`, full
audit); SECURITY §3 layered enforcement + admin's no-warehouse-tables rule; the Phase-5 DDL
grants (`nmc_officer`/`health_officer` NOLOGIN projection roles, `nagar` member of both —
`SET ROLE` wall) and `audit_logs` shape from `deploy/phases/05-postgres/migrations/
001_create_tables.sql`. Environment at start: 8/8 Applications green, node 5.5/13.65 GiB.

### G7b.2 — TDD: 27 hermetic tests, red → green

`query/tests/test_query.py` written first (collection error = red), then `app.py`. Final:
**27 passed**. Coverage: token absence/garbage/wrong-aud/denylisted-jti; single-SELECT AST
(SELECT/UNION pass; INSERT/UPDATE/DELETE/CREATE/DROP/TRUNCATE/GRANT, multi-statement ->
`non-select`; unparseable -> `parse-error`); table matrix incl. admin=none and unknown-role
fail-closed and users/sessions/audit_logs never queryable; PII columns blocked in select, alias
and WHERE, plus **star-expansion over a PII table**; `SET ROLE`/`RESET` wall ordering; audit on
allowed AND blocked with reason; 500-row cap; DB failure -> 503. Suite-driven fixes: truthful
`non-select` for DML sqlglot cannot parse (first-keyword fallback), semicolon stripped for the
wall-wrap subquery only (audit keeps SQL verbatim), stray argon2 import removed.

### G7b.3 — Image + pin

`mission/nagar-query-service:phase7b-1` (python:3.12-slim, uid 1000, tests not shipped).
Registry header `sha256:19133331732e656cbfc1d2f12186a830adf7f23f8c4006a71657db76e68186ee`
-> `digest-pins/` component -> **`PIN-MATCHES-REGISTRY`** string equality. Rendered tree
carries the pin; all 5 docs admitted by `kubectl apply --dry-run=client`.

### G7b.4 — Landing + the DB wall, proven from the database side

Commit `2f40f219` (code + manifests + Application + registration, one commit), mirror
`phase7b-1`, **9/9 Applications Synced/Healthy**. Before any E2E, the Phase-5 grant wall was
exercised directly on the primary:

```
SET ROLE nmc_officer;
 civic_visible = 2   (nmc_complaints readable)
SELECT count(*) FROM users;
 ERROR: permission denied for table users
```

### G7b.5 — E2E across service boundaries (contract-correct choreography)

First harness attempt failed with `Connection refused` from the query pod to auth-service —
**the NetworkPolicy was right and the harness was wrong**: queryService validates JWTs locally
(shared `nagar-jwt`, `sessions` denylist) and never calls auth; SECURITY §8 lists auth/admin/query
-> Postgres only. Re-choreographed: tokens minted via the real auth Service from an auth pod,
staged ephemerally into a query pod, gate matrix run there, `/logout` replayed cross-service.
Results:

```
GATE-MATRIX-OK (13/13 PASS)
  officer SELECT nmc_complaints -> 200 + rows (rows=2, incl. fixture)
  nmc_officer blocked from health table      | table-rbac
  health officer reads health table -> 200
  admin has NO warehouse tables              | table-rbac
  officer blocked from users                 | table-rbac
  PII name / phone blocked                   | pii-column
  star-expansion on PII table blocked        | pii-column
  UPDATE / DROP blocked                      | non-select
  unparseable blocked                        | parse-error
  no token -> 401        garbage token -> 401
JTI-DENYLIST-OK: logout at authService -> same token replayed at queryService -> 401
```

Audit evidence (audit_logs, source=queryService): **11 rows — 2 allowed, 3 table-rbac,
3 pii-column, 2 non-select, 1 parse-error** — every E2E attempt recorded with its verdict.

### G7b.6 — Cleanup

E2E fixtures (`source_system='e2e'` complaint + health row) and the two officer test users
deleted (`DELETE 1/1/2`); bootstrap admin + officer7a remain as documented artifacts. All
staged token/password files shredded in every auth and query pod (`/tmp` verified empty);
host scratch removed. Admin re-seed followed the established idempotent delete+seed pattern.

### G7b.7 — Platform gates

All **8 phase trees** build (LoadRestrictionsNone); **9/9 Applications Synced/Healthy**;
node **5.85/13.65 GiB (43%)**, disk 389G. New OPERATIONS §12.26 documents the
service-isolation E2E trap (mint tokens at auth; never widen the policy).

### Invariants touched

**I-1** — mirror/Argo only; out-of-band: §9.4 advance, admin re-seed (§9.1), and deletion of my
own E2E fixtures/test users. **I-2** — fresh connection + SET ROLE/RESET per request; re-runnable
gate. **I-3** — no secrets in git; tokens staged ephemerally and shredded. **I-4** — probes,
resources, PDB, NetworkPolicy enumerated to the letter of SECURITY §8. **I-5** — registry-header
digest, machine-verified. **I-6** — 4003 unchanged. **I-7** — Phase 9. **I-8** — no ADR: the
service-isolation behavior is the documented contract (SECURITY §8), not a deviation; §12.26
captures the operational lesson. **I-9** — scope: `deploy/phases/07-app-query/**` + two
app-of-apps files + mirror tag + docs. **I-11/I-12** — internal registry only; all trees build.

### Phase 7b exit criteria — met

- [x] `/query` executes (officer SELECT -> 200 + rows through the wall) — G7b.5
- [x] RBAC blocks correctly (health table, admin tables, auth tables) — G7b.5
- [x] Audit row written for every attempt, with reasons — G7b.5 (11/11 verified)
- [x] Bonus proofs: DB-side SET ROLE wall, cross-service jti denylist — G7b.4/G7b.5

---

## Phase 7c — enrichWorker (2026-09-30)

**Scope:** `deploy/phases/07-app-worker/` (fresh code per ADR-013) + app-of-apps registration.
Mirror `phase7c-1`; Application `nagar-phase7c-worker` Synced/Healthy. No pushes to any remote.

### G7c.1 — Contracts + the undocumented piece, resolved

ARCHITECTURE §3.3 (five raw topics → normalize → upsert; malformed → `nmc.complaints.dlq.v1`),
§3.2 invariants (duplicates answered idempotently on `sourceSystem + sourceRecordId`; Kafka
carries bucket/objectKey references, never bytes), §4.2 topic registry (frozen names; DLQ's
consumer is adminService 7f — the worker is its producer). The wire envelope itself was never
specified, so it is derived from the migration-001 column contract + §3.2 field names and now
documented in `worker/enrich.py` as the canonical contract for the 7e ingestion producer —
a discrepancy recorded here rather than assumed away. Kafka topology verified live: Strimzi
cluster `nagar`, plaintext listener, `nagar-kafka-bootstrap:29092`, topics pre-existing from
Phase 4.

### G7c.2 — TDD: 21 hermetic tests, red → green

`worker/tests/test_enrich.py` first (red), then `worker/enrich.py` as a **pure handler**
(`handle_message` → Outcomes) + thin confluent-kafka loop with commit-after-processing — no
broker needed for the suite. Coverage: per-topic table mapping; envelope validation (invalid
JSON / non-object / missing envelope fields / bad payload types / missing required fields /
unknown topic → DLQ with reason, never an exception); int/float coercion; camelCase→snake
mapping; upsert SQL shape (ON CONFLICT dedup key, enrichment refresh on conflict, identity
columns untouched); media refs carried, bytes never. Two test-authoring bugs (index-coupled
asserts, wrong tuple unpack) were fixed by making asserts column-name-derived — the
implementation itself needed no change. Final: **21 passed**.

### G7c.3 — Image + pin

`mission/nagar-enrich-worker:phase7c-1` (python:3.12-slim, uid 1000, tests not shipped,
confluent-kafka 2.11.1 + psycopg 3.2.9 pinned). Registry header
`sha256:81825d4745452c2d1fbd1da0a5a2d0449376304ec247a71bc20d078dd56bc7d2` → `digest-pins/`
component → **`PIN-MATCHES-REGISTRY`**. Worker manifests: NO Service and NO HTTP port
(CONVENTIONS §4 lists none for the worker), exec-based startup/liveness probes (a consumer has
no HTTP surface), replicas 1 (single consumer per group; ADR-006 substrate), egress exactly
Kafka 29092 + Postgres 5432 + DNS, §12.23 labels, writable /tmp (7a lesson).

### G7c.4 — Landing + live E2E (`topic→table`, `DLQ`, idempotent replay)

Commit `002f645b` (code + manifests + Application + registration, one commit), mirror
`phase7c-1`, **9/9 Applications Synced/Healthy**, pod 1/1 Running, subscribed to all five
topics. A transient bootstrap `Connection refused` (Strimzi listener still settling) was
absorbed by librdkafka retries — and produced the first accidental DLQ proof: a Phase-4-era
message on the topic was routed `-> dlq` (`invalid-envelope: missing or non-string
sourceSystem`) without crashing the loop. Deliberate E2E produced 3 messages to
`traffic.events.raw.v1`:

```
worker log:  -> upserted   (valid)
             -> upserted   (duplicate: same sourceSystem+sourceRecordId, severity low→high)
             -> dlq        (malformed {"broken":)
DB:  traffic_events | e2e | 7c-1 | severity=high | 1 ROW ONLY (redelivery refreshed, not duplicated)
DLQ-INSPECT-OK (consumer group dlq-inspect-7c):
  DLQ entry: invalid-json | body is not valid UTF-8 JSON | originalTopic: traffic.events.raw.v1
```

All three charter behaviors proven on the real surfaces: enrichment landed in the target table,
the at-least-once duplicate upserted (severity=high proves latest-wins), malformed input in the
DLQ with reason/detail/originalTopic/raw for adminService (7f) inspection.

### G7c.5 — Cleanup + platform gates

E2E fixture row deleted (`DELETE 1`); DLQ entries intentionally kept (that is the DLQ's
purpose); producer/consumer scratch files shredded from the pod and host. All **9 phase
trees** build; **9/9 Applications Synced/Healthy**; node **5.94/13.65 GiB (43.5%)**, disk 387G.

### Invariants touched

**I-1** — mirror/Argo only; out-of-band: §9.4 advance + deletion of my own fixture row.
**I-2** — upsert-on-conflict is the core design; commit-after-processing; redelivery proven
idempotent live. **I-3** — no secrets in git; DATABASE_URL via secretKeyRef. **I-4** — probes
(exec, worker-appropriate), resources, PDB, NetworkPolicy enumerated to real flows (§12.26
choreography applied: producer ran inside the worker pod, which owns the Kafka flow).
**I-5** — registry-header digest, machine-verified. **I-6** — 29092 unchanged. **I-7** —
Phase 9. **I-8** — no ADR: the envelope derivation is recorded as the 7e producer contract in
code + mission log; DLQ consumer/producer split is §4.2 verbatim. **I-9** — scope:
`deploy/phases/07-app-worker/**` + two app-of-apps files + mirror tag + docs. **I-11/I-12** —
internal registry only; all trees build.

### Phase 7c exit criteria — met

- [x] Events flow topic→table — G7c.4 (real produce, real upsert, DB row verified)
- [x] DLQ on malformed input — G7c.4 (`invalid-json` + accidental Phase-4-era
      `invalid-envelope`, both routed without crashing the loop)

---

## Phase 7d — slmService (2026-09-30)

**Scope:** `deploy/phases/07-app-slm/` (fresh code per ADR-013) + app-of-apps registration,
plus two cross-phase defect fixes the live E2E exposed (7b gate, phase-6 indexer). Mirrors
`phase7d-1..4`; Application `nagar-phase7d-slm` Synced/Healthy. No pushes to any remote.

### G7d.1 — Contracts + live parameter probe

`GET /health` (public, ollama/qdrant/query status) and `POST /ask` (JWT; NL→SQL+rows) from
ARCHITECTURE §4.1; §3.4 guardrails; SECURITY §3 ("generated SQL must pass the same queryService
gate — the LLM has no direct database access"). Undocumented detail — what identity /ask uses
against the gate — resolved as the **smallest consistent choice**: forward the CALLER's bearer
token (RBAC inheritance; no service identity exists in SECURITY §6.2, and the audit trail then
names the real human). Recorded in code + this log; no ADR needed (it *is* SECURITY §3's
sentence, made concrete). Before coding, the Phase-6 model contract was verified live:
`/api/generate` with `think:false` + `temperature:0` returns exactly "OK" (status 200).

### G7d.2 — TDD: 21 hermetic tests, red → green

All three backends mocked at module seams. Coverage: token absence/garbage/wrong-aud/
denylisted-jti; /health aggregation (503 with per-dep status); /ask happy path (SQL + rows +
role echoed, CALLER's token forwarded — asserted); prompt carries RAG context + SELECT-only +
PII rules; generate request shape (qwen3:1.7b, stream=false, **think=false, temperature=0**);
top_k=5; SQL extraction (fences, bare, `<think>` strip, empty → NoSQLError→502); gate verdicts
pass through verbatim (403 table-rbac for nmc_officer AND admin — slm does not duplicate RBAC);
backend failures → 503. Suite-driven fixes: health body shape (FastAPI nests `detail`), the
truthful pass-through rule (503→503), and catching RuntimeError seams as 503. Final: **21 passed**.

### G7d.3 — Image + manifests + landing

`mission/nagar-slm-service:phase7d-1`, digest machine-verified (`PIN-MATCHES-REGISTRY`).
NetworkPolicy egress exactly ollama:11434 + qdrant:6333 + query-service:4003 + postgres:5432
(jti denylist) + DNS — no other warehouse path. Commit `73fe71fb` (code + manifests +
Application + registration), mirror `phase7d-1`, **11/11 Applications Synced/Healthy**,
`/health` → `{"ollama":"ok","qdrant":"ok","query":"ok"}` from inside a pod.

### G7d.4 — E2E findings: RBAC inheritance proven; gate and indexer defects exposed

First run minted an **admin** token by mistake → `/ask` returned the gate's own verdict:
`403 table-rbac` passed through verbatim. A live negative proof that /ask inherits RBAC
(admins have no warehouse tables) — the positive path needed an officer token.

Officer run: Q2 (`which wards have open complaints?`) passed the FULL path — generated
`SELECT ward FROM nmc_complaints WHERE status = 'open'`, rows returned including the seeded
ward 9. Q1 (`how many complaints…`) was gate-blocked `pii-column`; the audit log (reading the
blocked SQL verbatim — the audit trail doing its job) showed the model emitted
`SELECT COUNT(*) FROM nmc_complaints`. Root cause: my 7b star-expansion hardening over-blocked
aggregation stars. A star as an aggregate argument projects no columns; the denylist contract
is about COLUMNS (ARCH §3.4). Fix: block only select-list stars; `SELECT *` still blocked.
Suite extended (`test_count_star_allowed_on_pii_table`, `test_select_star_still_blocked`) →
**29 passed**.

Recovery drill in passing: mid-diagnosis, qdrant began returning 500 on ALL searches
(`gridstore.rs:53 OutputTooSmall` — payload-storage segment corruption). Treated exactly as
documented (rebuildable cache): dropped `nagar_schema` and re-ran `/reindex` → 40 points,
search healthy again. This also surfaced a **phase-6 latent bug**: default async upserts made
the post-reindex count witness race (rebuild landed 40 while /reindex returned 500
`post-reindex point count mismatch`). Fixed with `?wait=true` upserts (image `phase6-3`,
machine-verified pin).

### G7d.5 — Prompt hardening + the ship-the-image lesson

Model variations also produced a PII-column COUNT and an invented `category='pothole'` filter;
prompt now forbids PII anywhere (incl. COUNT/WHERE) and inventing filter values. Landed as
`phase7d-2` — **and the first E2E on it still blocked COUNT(*): the 7b refinement was committed
but never built into an image; the tree still pinned phase7b-1.** Lesson recorded: a code fix
is not shipped until the image is rebuilt, re-pinned, and rolled — `git commit` is not a
deployment. Shipped as `phase7b-2` (digest `sha256:7c70081f…` machine-verified), mirror
`phase7d-4`.

### G7d.6 — Final E2E (`E2E-SLM-OK`, 8/8 PASS)

```
Q1: How many complaints are there in total?
  PASS 200 | SQL: SELECT COUNT(*) FROM nmc_complaints | rows=[{'count': 2}] | role=nmc_officer
Q2: Which wards have open complaints?
  PASS 200 | SQL: SELECT ward FROM nmc_complaints WHERE status = 'open' | rows=[{'ward': '9'}]
E2E-SLM-OK
```

Real NL → bge-m3 embed → qdrant RAG → qwen3:1.7b (temperature=0, think=false) → gate → rows.
Earlier negative proof preserved: admin `/ask` → 403 table-rbac pass-through.

### G7d.7 — Cleanup + platform gates

Fixture row + off7d test user deleted; staged tokens shredded in slm/auth pods; host scratch
removed. All **10 trees** build; **11/11 Applications Synced/Healthy**; node **8.62/13.65 GiB
(63%)** — qwen3 weights resident (OLLAMA_KEEP_ALIVE=24h) accounts for the rise; disk 382G, no
pressure conditions.

### Session lessons

(1) A mid-command `cd` poisoned a whole tool batch with relative paths — no changes landed
(none were committed, no k8s objects applied); re-ran from the project root with subshells.
(2) The ship-the-image lesson above (§12.27 candidate). (3) A persisted-token re-run against
recreated pods fails with "missing session" — the E2E restage is part of the choreography.

### Invariants touched

**I-1** — mirror/Argo only; out-of-band: §9.4 advances ×4, admin re-seed (§9.1), deletion of my
own fixtures/test users, and the qdrant collection drop+reindex (documented recovery of a
rebuildable cache, no durable data touched). **I-2** — reindex witness now deterministic
(wait=true). **I-3** — no secrets in git; tokens staged ephemerally, shredded. **I-4** —
probes/resources/PDB/NetworkPolicy to the letter. **I-5** — three new images (phase7d-1/2,
phase7b-2, phase6-3), all registry-header digests, all machine-verified. **I-6** — 4004
unchanged. **I-8** — no ADR: RBAC inheritance is SECURITY §3 made concrete; the COUNT(*)
refinement aligns the gate with ARCH §3.4's column-denylist wording (test-pinned); the indexer
fix restores I-2's original intent. **I-9** — scope: `deploy/phases/07-app-slm/**`, two
app-of-apps files, mirror tags, plus the two documented cross-phase defect fixes
(`deploy/phases/07-app-query/**`, `deploy/phases/06-vector-llm/indexer/**`) — the established
amendment precedent, both caught and proven live. **I-11/I-12** — internal registry only; all
trees build.

### Phase 7d exit criteria — met

- [x] `/ask` returns SQL + rows — G7d.6 (`E2E-SLM-OK`; real generation at temperature=0,
      think=false; execution through the queryService wall)
- [x] RBAC/security paths: admin /ask gate-blocked (table-rbac pass-through); PII denylist
      enforced against model output; denylisted jti rejected — G7d.4/G7d.6

## Phase 7e — ingestion backend (2026-09-30, k3d substrate)

Fresh rebuild per ADR-013 in `deploy/phases/07-app-ingestion/`. Contracts read before code:
ARCHITECTURE §3.2 (presigned flow, never-proxy-media, server-chosen topics, duplicate
idempotency), §4.1 endpoint registry, §4.2 frozen topics, the 7c wire envelope from
`worker/enrich.py` (producer must satisfy the consumer), SECURITY §6.2/§8 (secrets,
egress), Phase-4 producer conventions.

### G7e.1 — CrashLoopBackOff root-caused: k8s service-env injection (NaN port)

Standing re-verification found 7e pods crash-looping: `RangeError [ERR_SOCKET_BAD_PORT]
... Received NaN` at `runtime.js:60` (`server.listen(port)`), `port =
parseInt(process.env.INGESTION_PORT || '3000', 10)`. Local/image checks parsed 3000 fine —
the killer is Kubernetes service-link env: the Service named `ingestion` makes the kubelet
inject `INGESTION_PORT=tcp://10.43.x.x:3000` into pods created after the Service existed;
`parseInt("tcp://…")` = NaN. Hermetic tests cannot reproduce it (no service-env injection
outside k8s) — they passed while prod crashed. Fix: app env renamed `INGESTION_HTTP_PORT`
(default still the frozen 3000, I-6); commented at the read site; test seed updated.
Image `phase7e-2`, digest `sha256:5384c153ff48…` read from the registry header and
machine-compared with the rendered pin (`PIN-MATCHES-REGISTRY`). Pods Running. Recorded
as OPERATIONS §12.28.

### G7e.2 — Second boot defect exposed by real probes: minioOk fetched the bare S3 URL

With pods up, `/health` returned `503 {"api":true,"minio":false,"kafka":true}`. In-pod
probe: `GET http://minio…:9000/` → 403 (S3 auth on the bare base), `GET
…:9000/minio/health/live` → 200. `minioOk()` appended the health path only in its
env-less fallback branch. Fixed both branches to use `/minio/health/live`. Image
`phase7e-3`, digest `sha256:ac905eee1c81…` (same machine-verified pin flow). `/health`
→ `200 {"api":true,"minio":true,"kafka":true}` after Argo sync of the new mirror HEAD.
Recorded as OPERATIONS §12.29.

### G7e.3 — Third defect: sealed-secret pair drift (InvalidAccessKeyId on the real PUT)

API E2E first pass: presign 201, but the direct-to-MinIO PUT returned **403
`InvalidAccessKeyId`** — the commit gate then correctly answered 409 for the unverifiable
attachment (gate proven by accident). Root cause: SECURITY §6.2's dual-seal contract says
the `nagar-minio` (nagar-app) and `nagar-minio-server` (nagar-platform) seals carry the
same values, but nothing enforced it: the Phase-1 seal (`0facdc8c`) never matched the
Phase-3 server truth (`23f1efb5`); 7e's presigned PUTs were the first live consumer.
Compared copies by hashing decoded values (`base64 -d | sha256sum` — never printed):
`94b609f4…` vs `cb4a2b0e…` DRIFTED. Fix: re-sealed the consumer SealedSecret from the
server Secret piped with metadata overrides (`kubeseal` — plaintext only in the pipe,
never argv/disk/git), dropped the `mcHostLocal` key the server Secret carried but the
consumer's original seal did not, `kubectl apply` of the same-content git object
(sanctioned §9.4 transport exception), controller rewrote the Secret,
`rollout restart deploy/ingestion` (sanctioned §9 table). Post-fix hash equality:
`SECRET-ALIGNMENT-OK cb4a2b0e…`. Recorded as OPERATIONS §12.30.

### G7e.4 — Cluster-internal E2E (`E2E-RESULT`, §12.26 choreography)

JWT minted the real way: throwaway officer `off7e` created inside the auth pod via its own
`insert_user`/`hash_password`, then a real `POST /login` → 200 + `session_token` cookie
(Note: first mint attempt 401'd — I swapped `insert_user`'s hash/role args; row deleted,
re-minted correctly). NetworkPolicy egress blocks ingestion→auth-service by design, so the
token crossed pods via operator stdin only. Driver: `e2e/e2e-cluster.mjs` staged to pod
`/tmp` (Bearer header — 7e's `requireJwt` is Bearer-only). Results:

- `/health` 200 {api,minio,kafka all true}
- `POST /api/v1/uploads/presign` → 201 {uploads:[…], ttlSeconds:600}
- PUT bytes direct to MinIO via presigned URL → **200** (media never touches the API)
- `GET /api/v1/uploads/:id` → 200 intent {pending, bucket/objectKey/size/subject}
- `POST /api/v1/events` → **202 {eventId: evt-1afa9708…, topic:
  nmc.complaints.raw.restricted.v1}** — server-chosen frozen topic (§4.2)
- duplicate re-POST → **200 {duplicate:true}** with the same eventId (§3.2 idempotency)
- unknown department → 400 `unknown department`; missing `description` → 400
  `missing required payload field for complaints: description` (envelope contract)
- `GET /api/v1/events/:id` → 200 {status: published, topic, dedupKey}

Downstream leg: the 7c worker consumed the raw topic and enriched the row —
`nmc_complaints` shows the exact `event_id`, `source_system='e2e'`,
`source_record_id='e2e-7e-1790724073062'`, ward/category/status, `media_bucket='raw-media'`,
`media_object_key` set, and the payload description verbatim. Topic→API→Kafka→worker→table
proven end to end.

### G7e.5 — Cleanup + platform gates

Cleanup: `DELETE FROM nmc_complaints WHERE source_system='e2e'` (1), e2e sessions (1) and
user (1); pod `/tmp` staging removed; MinIO fixture object removed (`FIXTURES-REMOVED 1`,
deleted from the ingestion pod with the same S3 client); local token file shredded. The
driver stays versioned at `deploy/phases/07-app-ingestion/e2e/e2e-cluster.mjs` (outside
the image build context). Platform: 12/12 Applications Synced/Healthy (7e flipped
Degraded→Healthy); all 25 kustomize trees build with `--load-restrictor
LoadRestrictionsNone` (3 Components skipped by design); node 8.0/13.65 GiB (58%), disk
391G free.

### Session lessons

(1) The E2E stdout ate my first two staging attempts — one stdin per exec; stage the
driver and pipe the token in separate calls. (2) kubeseal round-trips every key of the
source Secret; trim keys the target's original seal didn't carry (sed on the sealed blob,
not plaintext edits). (3) Real-surface verification keeps paying: the crash (env
injection), the 403 (health path), and the InvalidAccessKeyId (secret drift) were all
invisible to the hermetic suite and each found within one probe of the real system.

### Invariants touched

**I-1** — mirror/Argo only; out-of-band: §9.4 mirror advances ×3, same-content SealedSecret
apply + sanctioned `rollout restart` (§12.30 remedy), deletion of my own fixtures/user.
**I-2** — unchanged (intents/keys all TTL'd; upserts idempotent). **I-3** — no secrets in
git; sealed blobs only; token staged ephemerally via stdin, shredded; plaintext never hit
argv/disk. **I-4** — probes/resources/PDB/NetworkPolicy to the letter; egress unchanged
(the E2E 401/403 path proved the policy, not a gap). **I-5** — phase7e-2/phase7e-3 digests
read from the registry header, machine-verified against the pin. **I-6** — 3000 unchanged.
**I-7/I-8** — no alerts touched; no ADR: all three defects are repairs toward documented
contracts (SECURITY §6.2 dual-seal, ARCH §3.2/§4.1), no architectural choice made. **I-9**
— scope: `deploy/phases/07-app-ingestion/**` (+ the pre-existing cross-phase SealedSecret
re-seal in `deploy/phases/01-substrate/secrets/`, the documented cross-phase defect-fix
precedent), two app-of-apps files, mirror tags. **I-10** — frozen files untouched. **I-11/
I-12** — internal registry only; all trees build.

### Phase 7e exit criteria — met

- [x] presign→PUT→event→Kafka E2E — G7e.4 (`E2E-RESULT` 202 commit + 200 duplicate + 200
      media PUT; topic→table enrichment witnessed in `nmc_complaints`)
- [x] Malformed input rejected per the envelope contract — G7e.4 (400 unknown-department,
      400 missing-description; unverifiable attachment 409 by the statObject gate)
- [x] Platform gates green — G7e.5 (12/12 apps, all trees build, headroom OK)

## Phase 7f — adminService (2026-09-30, k3d substrate)

Fresh rebuild per ADR-013 in `deploy/phases/07-app-admin/`. Contracts read before code:
ARCHITECTURE §4.1 adminService rows (all admin JWT), §4.2 DLQ registry (adminService
inspects; enrichWorker produces), SECURITY §3 (admin scope lives only here) / §6.2
(nagar-jwt, nagar-postgres-app) / §8 (egress = PG + Kafka + schemaIndexer + DNS), Phase-5
audit_logs DDL, the 7c DLQ wrapper from `worker/enrich.py record_to_dlq`.

### G7f.1 — TDD: 14 hermetic tests, red → green

Watched red (module absent → collection error), then green. The suite pins: the DLQ
wrapper byte-shape exactly as the 7c worker emits it ({dlqReason, detail, originalTopic,
raw} + topic/partition/offset), garbage-DLQ-message survival, bounded /dlq + /audit-logs
reads with validation-rejected (422) out-of-range limits, per-dependency health booleans
with `all` = AND, officer 403 on every admin endpoint, cross-service jti denylist (7b
lesson), wrong iss/aud 401, public / and /dbcheck. The TDD loop caught a real bug before
any deploy: `all` was initially hardcoded `True` in the response literal.

### G7f.2 — Image + manifests + landing

Image `phase7f-1`, digest read from the registry header and machine-compared with the
rendered pin (`PIN-MATCHES-REGISTRY`). Service `admin-service` :4001 (tier convention
name — no `*_PORT` env read exists anywhere in the image, so the 7e service-link class
cannot recur), Deployment ×2 with pod+container securityContext, writable /tmp emptyDir,
probes, PDB minAvailable 1, NetworkPolicy egress = postgres-rw 5432 + Strimzi 29092 +
schema-indexer 4005 + DNS only. Application `nagar-phase7f-admin` + apps registration in
the same commit; mirror `phase7f-1` → Application created, then Kyverno BLOCKED the
Deployment: pod-level `runAsNonRoot`/`seccompProfile` mandatory (SECURITY §5 autogen
policy) — client dry-runs cannot see admission; fixed (commit c80d76cb), mirror
`phase7f-2` → Synced/Healthy, probes green through the policy.

### G7f.3 — Real admin JWT + first E2E pass (harness exposes three findings)

Admin + officer tokens minted as throwaway fixtures (`adm7f` user_id e2e-7f-001, `off7f`
user_id e2e-7f-002) INSIDE the auth pod with its own hash/insert code, then real
`POST /login` → 200 cookies, staged to the admin pod via operator stdin only. First
E2E-RESULT findings: (1) `/dlq` 503 — my `position()` tuple-unpack (TopicPartition
objects are not tuples); (2) `schemaIndexer:false` — phase-6's ingress policy for 4005
was namespace-only; its own comment pre-authorized the widening ("one-rule change when
7f ships"), applied per the 7b/6 cross-phase precedent (commit 42ecaab, mirror
phase7f-3); (3) officer matrix 401-not-403 — my `$(head -1)` stdin bug, not a code bug.

### G7f.4 — DLQ binding gauntlet, then the full green E2E (`E2E-RESULT`, 8/8 PASS)

Three successive confluent-kafka 2.11.1 binding quirks, each probed live against the
worker image (same lib pin) before patching: `timeout=` keyword rejected on
`get_watermark_offsets`; the `(topic, partition:int)` form rejected
("expected cimpl.TopicPartition" — needs a TopicPartition OBJECT); and committing
OFFSET_END placeholders fails `_NO_OFFSET`, so the tail is now STATELESS (watermark
end-offsets, nothing committed — inspection never mutates cluster state, I-2). Images
phase7f-3/4/5, all digests registry-header read + machine-verified. Final E2E
(mirror phase7f-6, rev 6578379f):

- `/health/cluster` 200 {db:true, kafka:true, schemaIndexer:true, all:true}
- `/dlq?limit=20` 200 — 3 entries: offset 0-1 are the PRE-EXISTING phase-4 gate
  evidence (untouched, documented artifacts); offset 2 is MY fixture B
  (`e2e7f-malformed-1790727526008`): a structurally invalid envelope produced directly
  to `nmc.complaints.raw.restricted.v1` from the worker pod, DLQ'd by the 7c worker
  ("missing or non-string eventId", originalTopic + raw preserved byte-exact) — the
  full producer→DLQ→inspect round-trip live
- `/audit-logs?limit=5` 200 — real 7b/7d gate rows (allowed + pii-column blocked)
- officer token → 403 on all three admin endpoints; no token → 401
- adminService → ingestion connection refused = NetworkPolicy enforcing exactly the
  documented flows (SECURITY §8) — refusal IS the proof
- fixture A out-of-band from an ingestion pod: `POST /api/v1/events` missing
  description → 400 "missing required payload field for complaints: description"
  (API layer rejects before Kafka; no DLQ entry created — correct per contract)

### G7f.5 — Platform gates + cleanup

13/13 Applications Synced/Healthy; ALL-TREES-BUILD (25 trees, Components skipped by
design); node 8.4/13.65 GiB (61%), disk 382G free. Cleanup: fixture users + sessions
deleted (2+2), pod staging removed, token file shredded. DLQ messages retained
(append-only inspection evidence; offsets 0-1 pre-date 7f, offset 2 documented here).
Driver versioned at `deploy/phases/07-app-admin/e2e/e2e-cluster.py` with the corrected
read-per-line choreography in its header.

### Session lessons

(1) Client dry-runs cannot see admission: Kyverno's pod-security policy blocked a
deployment whose container-level securityContext looked complete — pod-level context is
a separate mandatory block. (2) When a live harness errors inside a vendor binding,
probe the exact call shape in-cluster against the same pinned version BEFORE patching —
three quirks resolved in one probe cycle each. (3) Stdin choreography is part of the
E2E: one `read -r` per token, documented in the driver header. (4) A phase's own
comments can pre-authorize future widening (4005 ingress) — read them before treating a
refusal as a defect.

### Invariants touched

**I-1** — mirror/Argo only; out-of-band: §9.4 mirror advances ×6, deletion of my own
fixtures/users. **I-2** — DLQ inspection now stateless (no commits at all). **I-3** —
sealed blobs only; tokens staged ephemerally via stdin, shredded. **I-4** —
probes/resources/PDB/NetworkPolicy/pod-securityContext to the letter (Kyverno-enforced).
**I-5** — phase7f-1..5 digests registry-header read, machine-verified. **I-6** — 4001
unchanged. **I-7** — no alerts touched. **I-8** — ADR-022 written (/vector/resync
deferral; adminService consumer-group choice documented in code). **I-9** — scope:
`deploy/phases/07-app-admin/**`, app-of-apps files, mirror tags, plus the pre-authorized
cross-phase 4005 ingress widening in `deploy/phases/06-vector-llm/networkpolicies.yaml`.
**I-10** — frozen files untouched. **I-11/I-12** — internal registry only; all trees build.

### Phase 7f exit criteria — met

- [x] `/health/cluster` all-up — G7f.4 (db/kafka/schemaIndexer all true, all:true)
- [x] `/dlq` live — G7f.4 (3 real entries incl. a live malformed→worker→DLQ round-trip)
- [x] `/audit-logs` live — G7f.4 (real allowed/blocked rows from the 7b/7d gates)
- [x] Non-admin 403 + platform gates — G7f.4/G7f.5 (13/13 apps, all trees build)
## Phase 7g — frontend + vault-ui (2026-09-30, k3d substrate)

Fresh rebuild per ADR-013 in `deploy/phases/07-app-ui/` (both UI apps in one phase
subtree; frozen legacy dirs stay deleted, I-10). Contracts read before code:
CONVENTIONS §4 (3001 public edge target, 5173 dev overlay never edge-exposed),
ARCHITECTURE §3.4 (UI chatbot consumes slm `/ask`) + Tier 9 dependency ordering,
SECURITY §2/§3/§6.2/§8, the deployed contracts of authService (`/login` Credentials =
{username,password}, Set-Cookie httponly host-only; `/whoami`), slmService (`/ask`
{question≤2000} → {sql, rows, row_count, role}; 403 gate verdicts structured),
ingestion (`/api/v1/events` envelope), plus the admin-RBAC rule proven in 7b/7f.
Anything undocumented was decided as the smallest consistent choice and recorded in
ADR-023: **server-side BFF** (browser talks only to :3001; cookie relayed as Bearer
server-side; login body whitelisted; Set-Cookie re-emitted host-only/httponly;
`/ask` responses whitelisted to {sql, rows, row_count, role}) and a **proxying
injector** (fixed method+path allowlist, credential redaction in logs, operator-staged
ephemeral token at pod `/tmp/injector-token`).

### G7g.1 — TDD + build: red → green, Next standalone

12 hermetic tests watched red (modules absent → import failure), then green: cookie→
Bearer extraction, login-body whitelisting (legacy `user_id` field dropped),
Set-Cookie rewriting (host-only/httponly preserved, Domain never set), `/ask` response
whitelist, frozen-registry upstream defaults + env overrides; injector target
resolution (rejects scheme-relative/absolute/`..` escapes), method+path allowlist,
header redaction, synthetic envelope construction. Test/impl contract mismatch on the
cookie-attr key caught by the suite and fixed in the TEST (impl shape was the sane
one). Next 16.3.1 standalone build clean (routes: /, /login, /dashboard, /api/*).

### G7g.2 — Landing: 14/14 Apps on the first cycle; qdrant panic #2 recovered

Images `phase7g-1` (frontend, vault-ui) — digests registry-header read, machine-verified
(`PIN-MATCHES-REGISTRY`, both). The 7f lesson was pre-applied (pod-level securityContext
from the start) and Kyverno admitted first try: Application `nagar-phase7g-ui` +
registration same commit, mirror `phase7g-1` → **14/14 Applications Synced/Healthy,
no human touch**. Frontend polished to `phase7g-2` (+`/api/whoami` route, structured
gate-verdict pass-through; digest re-verified; mirror `phase7g-2`). During E2E the
officer/admin asks 503'd with "retrieval or generation backend unreachable" while slm
`/health` was ok and ollama embed fine: direct qdrant probe showed the SECOND segment-
corruption panic of the mission (`OutputTooSmall` unwrap, §12.33). Recovered via
schemaIndexer `POST /reindex` → `{upserted: 40, points_count: 40}`; search probe
200 with 5 hits; `/ask` immediately green. No durable data touched (rebuildable cache,
established precedent).

### G7g.3 — E2E through the UI surface (`E2E-RESULT`, 8/8 PASS + injector round-trip)

Fixtures minted inside the auth pod (e2e-7g-001 adm7g/admin, e2e-7g-002 off7g/officer,
e2e-7g-004 offhealth7g/ROLE_HEALTH_OFFICER), passwords via operator stdin only, driver
run INSIDE a frontend pod (§12.26: the BFF is the subject; its chartered egress flows
are the ones under test):

- officer `/api/login` → 200 {status:ok, role:nmc_officer} with **httponly Set-Cookie
  relayed** (token never enters browser JS)
- officer `/api/whoami` → 200 {sub: e2e-7g-002, role: nmc_officer} — cookie→Bearer
  relay server-side
- officer `/api/ask` → **200 {sql: "SELECT COUNT(*) FROM nmc_complaints", row_count: 1,
  role: nmc_officer}** — real NL → bge-m3 → qdrant RAG → qwen3 (temperature=0,
  think=false) → queryService with the OFFICER's token → rows, all through the BFF
- admin `/api/ask` → **403 {reason: table-rbac, verdict: blocked}** — the SECURITY §3
  admin wall proven through the UI (pass-through of the structured verdict)
- `/api/ask` without cookie → 401; bad credentials → 401 (rate-limit still upstream)
- ROLE_HEALTH_OFFICER `/api/ask` (health-camps question) → **200** (the role 7b's wall
  gates for health tables — allowed where chartered)
- PII probe ("patient phone number and name") → **403 {reason: pii-column}** — the
  denylist enforced through the UI
- injector: staged admin token at `/tmp/injector-token` → POST form-equivalent →
  **202 {eventId: evt-f1e857b6…, topic: nmc.complaints.raw.restricted.v1}** →
  7c worker enriched the row (`source_system='vault-ui'`, ward 7, description verbatim)

Two operator-side stumbles documented for the record: staged the fixture PASSWORD
instead of the minted token (injector correctly 401'd it — the auth chain working);
`printf '%s'` without newline made `read` kill the pipe chain. Both fixed in-place.

### Platform gates + cleanup

14/14 Applications Synced/Healthy; ALL-TREES-BUILD (27 trees incl. 07-app-ui);
node 8.3/13.65 GiB (60%) after +3 UI pods; disk 376G free. Cleanup: injector row
deleted (1), fixture users+sessions deleted (3 users, 2 sessions), pod staging
removed (driver + injector token), local token/password files shredded. The frontend
driver is versioned at `deploy/phases/07-app-ui/e2e/e2e-frontend.mjs` with the
read-per-line choreography in its header.

### Session lessons

(1) First mirror-cycle Healthy with zero admission retries — pre-applying the 7f
pod-securityContext lesson is the difference between one cycle and four. (2) "Backend
unreachable" can be a lie told by a panicking cache: health checks metadata-green,
search panics — probe the real operation, not the health endpoint (§12.33). (3) Staging
the wrong secret class (password vs token) failed CLOSED everywhere it touched — the
contract work of 7a–7f is what made the mistake cheap.

### Invariants touched

**I-1** — mirror/Argo only; out-of-band: §9.4 mirror advances ×2, qdrant `/reindex`
recovery (documented, rebuildable cache), deletion of my own fixtures. **I-2** —
injector token TTL'd by process lifetime; nothing durable written. **I-3** — no secrets
in git; all fixture material ephemeral + shredded. **I-4** — probes/resources/PDB
(frontend ×2)/NetworkPolicies/pod-securityContext to the letter. **I-5** — phase7g-1/2
digests registry-header read, machine-verified. **I-6** — 3001/5173 unchanged. **I-7**
— no alerts touched. **I-8** — ADR-023 written (BFF + injector proxy; the one
architectural choice 7g required). **I-9** — scope: `deploy/phases/07-app-ui/**`,
app-of-apps files, mirror tags. **I-10** — frozen files untouched. **I-11/I-12** —
internal registry only; all trees build.

### Phase 7g exit criteria — met

- [x] Browser-flow E2E: login, dashboard, ask — G7g.3 (real logins + cookie relay,
      whoami identity, officer ask with RBAC-inherited rows through the full SLM chain)
- [x] Authz boundaries enforced where chartered — G7g.3 (admin 403 table-rbac,
      PII 403, health-officer allowed, no-cookie 401, bad-creds 401)
- [x] Injector flow — G7g.3 (202 → Kafka → worker → `nmc_complaints` row)
- [x] Platform gates — G7g.2/G7g.5 (14/14 apps, all trees build, headroom OK)

**Phase 7 complete: all seven app-tier services rebuilt fresh and verified live.**
Next charter: Phase 8 — Edge & TLS (Traefik IngressRoutes, cert-manager internal CA,
CORS, rate-limit middleware; browser presigned PUT from the frontend origin).

## Phase 8 — Edge & TLS (2026-09-30, k3d substrate)

Charter: Traefik in-cluster behind a LoadBalancer Service, cert-manager internal-CA
leaf certificates, CORS + rate-limit middlewares, TLS termination at the edge with
in-cluster traffic untouched (ADR-024; PHASES.md §2). All bring-up defects were fixed
through git via the mirror cycle — 13 commits, `16a4052d`..`22a263b8`, each recorded in
ADR-024 field repairs (a)–(d): dedicated ping entrypoint (k3s-EPHT theory tested and
falsified on the pinned image), CA Certificate in the cert-manager namespace, leaf
certificates split per route namespace, COOKIE_SECURE landed in the 7a manifest (both
cross-tree patch forms proven inert or invalid), vendored 10-CRD v3.5 bundle + RBAC
repairs (nodes, endpointslices, per-namespace middlewares/TLSOptions), one NetworkPolicy
per widened upstream, parenthesized host disjunctions (`&&` binds tighter than `||`),
strip-prefix map for upstreams that serve native paths, cold-config reload annotation.
Mirror tags phase8-1..phase8-15; phase8-15 Synced/Healthy across all 15 Applications.
Full login proof (openssl chain to `CN=nagar-edge-ca`, `GET /auth/` 200, `POST /auth/login`
setting a `Secure` cookie) was green before this section's gate run.

### G8.1 — TLS: leaf chains to the internal CA; protocol floor holds

Re-proven against the live edge (inline port-forward spawn→prove→kill on a fresh port,
CA at `/tmp/nagar-edge-ca.pem` re-extracted from `cert-manager/nagar-edge-ca-keypair`,
558 B, `notAfter 2027-09-30`):

    $ openssl s_client -connect 127.0.0.1:8448 -servername k3d.nagar.internal \
        -CAfile /tmp/nagar-edge-ca.pem -verify_return_error
    depth=1 CN=nagar-edge-ca
    depth=0 CN=k3d.nagar.internal
     0 s:CN=k3d.nagar.internal
       i:CN=nagar-edge-ca
    Verify return code: 0 (ok)

Served leaf: `subject=CN=k3d.nagar.internal`, `issuer=CN=nagar-edge-ca`,
SAN `DNS:k3d.nagar.internal, DNS:k3d-nagar.localhost` — exactly the ADR-024 §4 pair.
Protocol floor (`edge-tls-options` minVersion VersionTLS12): TLS-1.1-only handshake
`curl --tls-max 1.1` → `000` (curl exit, handshake refused); TLS-1.2-only → `200`.
Two self-inflicted instrument defects recorded for honesty: (1) the first chain probe
passed curl's `--ssl-no-revoke` to openssl, which has no such flag and silently produced
no output — rerun cleanly; (2) `curl --tlsv1.1` sets a *floor*, so it climbed to 1.2 and
"passed" — the ceiling flag `--tls-max` is the correct probe.

### G8.2 — CORS: preflight allowlist behaves as configured

Preflight on `/minio/raw-media/...` (deployed `edge-cors` read before probing):

    Origin: https://k3d-nagar.localhost  ->
    HTTP/1.1 200 OK
    Access-Control-Allow-Origin: https://k3d-nagar.localhost
    Access-Control-Allow-Methods: GET,PUT,POST,HEAD,OPTIONS
    Access-Control-Allow-Headers: Content-Type,Authorization,x-amz-date,x-amz-content-sha256,Range
    Access-Control-Allow-Credentials: true
    Access-Control-Max-Age: 600

    Origin: https://evil.example.com ->
    HTTP/1.1 200 OK
    Access-Control-Allow-Methods: ...            # same methods/headers/max-age echo
    (no Access-Control-Allow-Origin — the browser-enforced negative; CORS blocks in
     the client, so the middleware correctly reflects nothing for foreign origins)

Non-preflight GET with allowed Origin: `Access-Control-Allow-Origin` + `Vary: Origin`
(addVaryHeader) + MinIO's `Access-Control-Expose-Headers`, and the edge-headers STS
header present on the same response (`Strict-Transport-Security: max-age=31536000;
includeSubDomains`) — headers and CORS compose on one router.

### G8.3 — Rate limit: both layers fire, correctly attributable

32 rapid `POST /auth/login` (wrong credentials) through the edge:
requests 1–10 pass to auth (`401 {"detail":"invalid credentials"}`), 11–21 answer
`429 {"detail":"login rate limit exceeded"}` with **no** Retry-After (FastAPI JSON —
auth's in-app limiter), 22–27 answer `429 Too Many Requests` **with `Retry-After: 3→1`**
(Traefik's edge middleware — plain-text body, Retry-After header), 28 flips back to the
app shape (a sliding-window slot freed mid-burst), 29–32 edge shape again
(`Retry-After: 6→5`). Attribution is unambiguous: Traefik's 429 carries `Retry-After`
and a non-JSON body; auth's 429 is the JSON detail form. Defense-in-depth shown live:
edge bucket (average 10 / burst 20 / 1m on the whole `/auth` router) exhausts behind the
app limiters, then meters recovery.
Finding (not a defect): auth's limiter is an in-process per-IP deque (5/min) with
**2 replicas**, so the effective app-side cap observed was ~10/min and refills landed
per-pod mid-burst — the edge bucket is the only global control, which is exactly why it
belongs at the edge. The 7a contract tests the single-process limiter and is unchanged.

### G8.4 — Presigned PUT through the edge: bytes land intact

`POST /api/v1/uploads/presign` with the admin8 Bearer JWT via the edge `/api` route →
201-shaped body: `uploads=1, ttlSeconds=600`, `attachmentId 9044134c-8675-475a-9356-1d832f5840e8`,
`bucket raw-media`, `objectKey events/9044134c-…/g8-edge-proof.bin`.

**Discrepancy, recorded:** the minted URL host is
`minio.nagar-platform.svc.cluster.local:9000` — cluster-internal DNS that no browser can
resolve. 7e's presigner endpoint comes from `MINIO_URL` and offers **no external-host env**
(`runtime.js` reads only `MINIO_URL`; the Deployment sets the in-cluster Service URL), so
the literal browser flow cannot be exercised end-to-end today. Proven instead by the
equivalent path, with the discrepancy logged for the phase closeout: (1) an edge-origin
presigned PUT URL (`https://k3d.nagar.internal:8448/raw-media/...?X-Amz-...`) was minted
*inside* the ingestion pod via its own SDK+secret env (credentials never left the pod;
`X-Amz-Credential`/`X-Amz-Signature` masked on display); (2) the browser-adapter path
rewrite `/raw-media/...` → `/minio/raw-media/...` applied (SigV4 signs only the host
header, so the edge strip is signature-neutral — and the first attempt without the
rewrite proved the point by falling to the `/` catch-all: 404 + Next.js HTML); (3) PUT
through the edge → `HTTP/1.1 200 OK`, `Etag: "ac2bf4ac11014d92e9d8e3fd6ed99ccb"`.
Byte verification in-cluster (fixture pod `g8-mc-verify`, nagar-platform, mc + the
pod-local `nagar-minio-server` secret): `mc stat` reports `Size: 62 B`,
`ETag ac2bf4ac11014d92e9d8e3fd6ed99ccb`, `Content-Type application/octet-stream`; stored
sha256 `f9345d8b4081a4a0bb98723acc7ac36c53136dffa8724f702100ea64b3f4169d` == local sha256;
local md5 == PUT ETag == stat ETag. Verifier fixture kept at
`deploy/phases/08-edge/e2e/fixtures/g8-mc-verify-pod.yaml` (raw Pod, not in the phase
kustomization — the tree still builds); its bring-up re-earned three older lessons and
added one: PodSecurity `restricted` + Kyverno `require-resources-limits` both gate ad-hoc
pods (I-4 is enforced at admission, not on trust), `envFrom` injects secret keys verbatim
(`accessKey`, not `MINIO_ACCESS_KEY` — map explicitly), pods are immutable (delete +
re-apply), and MinIO briefly refuses fresh connections right after its own restart —
the verifier retries. Verifier pod deleted after the proof.

### G8.5 — Authz negatives: 401 without a session, 403 without the role

Officer seeded through the sanctioned admin-gated creation path (7a contract), never
seed_admin: `POST /auth/create` with the admin Bearer → `200
{"status":"ok","user_id":"officer8-279fa8df","username":"officer8","role":"nmc_officer"}`
(random 28-hex password, never displayed; user created in-band to prove the /create gate
itself). Officer login 200; `whoami` echoes `role: nmc_officer`.

    GET /admin/health/cluster, no JWT      -> 401 {"detail":"missing session"}
    GET /admin/health/cluster, officer JWT -> 403 {"detail":"admin role required"}
    GET /admin/dlq,             officer JWT -> 403
    GET /admin/audit-logs,      officer JWT -> 403
    GET /admin/health/cluster, admin JWT   -> 200 {db, kafka, schemaIndexer, all}

SECURITY §3 holds at the edge: identity (401) and role (403) are enforced upstream by
adminService, with the admin-only contrast proving the 403 is role-based, not route
breakage. Officer cookie jar shredded after the run.

### G8.6 — In-cluster flows unaffected by the edge (no StripPrefix regression)

- BFF-native path: exec in a frontend pod → `auth-service.nagar-app.svc.cluster.local:4000/whoami`
  with the admin Bearer → `status: 200 | role: admin | sub set: true` — in-cluster traffic
  never touches the edge, native `/whoami` path intact.
- Edge `/api` is VERBATIM (no strip): `GET /api/v1/events/evt-g8-nonexistent` →
  `404 {"detail":"unknown eventId"}` — ingestion's native contract, prefix not stripped.
- Edge `/` catch-all serves the frontend (`307`, 4948 B body).

### Substrate event during the gate run (documented, no git change)

Freebuff restarted mid-run: Docker Desktop engine down → k3d containers came back on
their own (server-0, serverlb), broker `nagar-dual-role-0` restarted and reloaded
metadata from disk (KRaft durability), and ingestion exhausted restart backoff while
Kafka was down (`ECONNREFUSED :29092` crashloop). Recovery: relaunched Docker Desktop
detached (`Start-Process`), regenerated the kubeconfig via `k3d kubeconfig get nagar`
(sed host.docker.internal→127.0.0.1; API port **57306 again**), re-extracted the CA,
waited for the broker's readiness, then cleared ingestion's backoff by deleting its pods
(Deployment recreated them; no live-state drift). All 15 Applications back to
Synced/Healthy. Noted: fast-failing consumers should survive broker restarts more
gracefully, but this is substrate lifecycle, not a phase-8 defect.

### Session lessons

(1) `--ssl-no-revoke` is a curl/schannel flag — openssl rejects unknown options
silently in pipelines; check tool boundaries before composing flags. (2) `curl --tlsvN`
is a floor; protocol-floor proofs need `--tls-max`. (3) Windows Python has no `/dev/stdin`
— keep secret material in shell variables, never through stdin files. (4) `kubectl run
--overrides` does not survive MSYS quoting — write small verbatim YAML fixtures instead
(and remember pods are immutable: delete + re-apply). (5) `envFrom` injects secret keys
verbatim; images expecting canonical variable names need explicit `secretKeyRef` envs.
(6) After an engine restart, statefulsets self-heal but fast-crash consumers exhaust
restart backoff — clear with a pod delete, then let the Deployment converge. (7) An
in-memory per-IP limiter behind N replicas is N× weaker than its spec; the only global
rate control is the one at the shared edge.

### Invariants touched

**I-1** — all changes via git (this log, ADR-024 §6 correction, verifier fixture); live
ops limited to pod deletions of Deployment-owned pods + the fixture, documented above.
**I-2** — verifier is an idempotent retry loop. **I-3** — officer password generated and
never displayed; cookie jars and presigned URLs shredded; credentials masked in any
shown output. **I-4** — fixture pod passed PodSecurity restricted + Kyverno resource gates
at admission. **I-5** — fixture image digest-pinned. **I-6** — no ports touched.
**I-7** — no alerts touched. **I-8** — ADR-024 §6 strip-map falsification corrected in
the ADR itself. **I-9** — changes confined to `agentic/mission-log.md`,
`docs/DECISIONS.md`, `deploy/phases/08-edge/e2e/fixtures/`. **I-10** — frozen files
untouched. **I-11/I-12** — internal-registry digest only; no manifest tree altered.

### G8 E2E gates — 6/6 GREEN

TLS chain ✓ · CORS allow/deny ✓ · rate limit attributed ✓ · presigned PUT byte-intact
(with browser-host discrepancy recorded) ✓ · authz 401/403 ✓ · in-cluster paths intact ✓.

### G8.7 — Closeout: platform gates, charter exit criteria, ledger flip

Platform gates, live:

    15/15 Applications Synced/Healthy (nagar-system, incl. nagar-phase8-edge)
    ALL-TREES-BUILD: 39/39 kustomization trees build (top-level 14/14)
    node k3d-nagar-server-0: 246m CPU, 6735Mi/48% memory
    disk: 356G free (63% used)
    g8 fixtures remaining in cluster: 0 (verifier pod deleted after G8.4; its manifest
      stays versioned at deploy/phases/08-edge/e2e/fixtures/ for re-use/audit)

Charter exit criteria, exercised verbatim from OPERATIONS §11:

    step 1: curl -sf https://<edge>/auth/ | grep ok
            -> {"status":"ok","service":"authService"}  SMOKE-1-OK
    step 2: curl -si -X POST https://<edge>/auth/login -d '{...}' | head -1
            -> HTTP/1.1 200 OK
               Set-Cookie: session_token=<redacted>; HttpOnly; Max-Age=3600;
                          Path=/; SameSite=lax; Secure

Invocation finding: the script's literal curl form silently returns `000` on this
substrate — the host has no 80/443 mapping (ADR-024) AND its trust store does not hold
the internal CA. Documented as an invocation note in §11 (port-forward + `--resolve` +
`-k` + `--ssl-no-revoke`; one-shot spawn→poll→prove→kill), with the troubleshooting row
**§12.34**. The probe/poll step exists because cold forwards occasionally serve nothing for
the first seconds. Securing smoke step 2 required the seeded admin8 credential set and the
`Secure` cookie landed by the phase — the charter's HTTPS requirement is exactly what the
COOKIE_SECURE flip (field repair d) was for.

Second §12 row from this session: **§12.35** — `envFrom` injects secret keys verbatim;
canonical-name consumers (`MINIO_ACCESS_KEY`) see empty vars and fall back to anonymous
(the G8.4 verifier's AccessDenied detour).

**Ledger flip: Phase 8 → Done (2026-09-30, k3d substrate)** in `docs/PHASES.md` §1,
with the charter block carrying the exit evidence and the one recorded deviation: the
literal browser-origin presigned PUT is blocked upstream by 7e's presigner (no external-
host env — minted URLs carry cluster-internal DNS), proven instead via the equivalent
edge path; `PRESIGN_PUBLIC_URL` in 7e is the follow-up that closes it. AGENTS.md §7
refreshed: Phases 1–8 done, 9–10 remain.

Charter exit criteria — met (with the recorded deviation above). **Phase 8 complete:
the platform has a real edge — TLS by the internal CA, CORS, rate limiting, and the
presigned-PUT route — with in-cluster paths untouched.**
Next charter: Phase 9 — Observability & hardening (Prometheus + Loki, full Kyverno set,
NetworkPolicy completion, alert rules with runbook anchors, restore drill evidence).

## Substrate maintenance — Docker storage optimization (2026-09-30, k3d substrate)

Trigger: host disk pressure from `docker_data.vhdx` at 123,692,122,112 B (123.7 GB).
Measured disposition (nothing guessed): `docker system df` → Images 3/428.1 MB,
Containers 3/2.187 MB, Local Volumes 6/**71.29 GB** (100% active), Build Cache 223
entries/**25.72 GB** (100% reclaimable). Volume forensics: the five k3d anonymous hex
volumes map to k3s internal dirs on `k3d-nagar-server-0` (/var/log, /var/lib/cni,
/var/lib/kubelet, /var/lib/rancher/k3s) plus the shared `k3d-nagar-images`, and one to
the registry's /var/lib/registry — i.e. ALL visible volume bytes are k3d mission state,
not stray Docker data. In-volume du: k3s containerd image store **45 GB** (every mission
tag ever pulled), live PVC storage **4.9 GB** (Postgres/Kafka/MinIO/Qdrant/Ollama —
protected), kubelet 633 MB, registry payload **21.2 GB** (every version ever pushed).
Plan (user-approved): backup → build-cache/dangling prune → registry tag-prune + GC →
destructive rebuild with project-named volumes → Argo resync from git → elevated VHDX
compaction → weekly hygiene automation; executed in passes, evidence per phase.
Qdrant collections and Ollama models are intentionally NOT backed up: both rebuild
idempotently from git-driven Jobs (schema-indexer re-embeds; models Job re-copies).

### Phase A — backup before any destructive step (proof-carrying)

Target dir `C:\Users\styli\.k3d\nagar-backup-2026-09-30\`.

**A1 — nagardb logical dump.** Topology: no CNPG CRD in this substrate — Postgres is a
plain StatefulSet (`postgres-1` primary: `pg_is_in_recovery()=f`, `postgres-2` replica:
`=t`). Auth learned live: the CNPG socket at `/controller/run` enforces peer auth
(FATAL), and the database is **`nagardb`** (not `nagar`) — TCP + `PGPASSWORD` from the
`nagar-postgres-bootstrap` secret works. Dump from the primary:

    pg_dump -h 127.0.0.1 -U nagar -d nagardb --no-owner --no-privileges
    → exit 0, 22,846 B, 8/8 CREATE TABLE (audit_logs, ev_bus_telemetry,
      health_camp_records, nmc_complaints, sessions, traffic_events, users,
      water_sensor_readings), 8 COPY data sections, users rows present.

Roles (`nmc_officer`, `health_officer`) are phase-5 DDL objects, re-created on restore.

**A2 — raw-media bucket mirror.** In-cluster verifier pattern (fixture
`deploy/phases/08-edge/e2e/fixtures/nagar-minio-backup-pod.yaml`, PodSecurity-restricted,
Kyverno-gated, `nagar-minio-server` secretKeyRef envs — credentials never leave the
pod): `mc mirror --preserve v/raw-media` → **1 object, 62 B** (the G8.4 proof object;
the bucket is otherwise empty post-7g-cleanup) → tar+gzip → `SHA256SUMS` in-pod →
BACKUP-READY gate → host copy-out.

Transport lessons (three stacked Windows/MSYS traps, each now named):
1. `kubectl cp` is unusable Git-Bash→host here: an MSYS dest (`/c/...`) is not recognized
   as a local file; a Windows dest (`C:/...`) is misread as a REMOTE path (drive colon).
2. `kubectl exec -- cat /backup/...` — argument-position POSIX paths get Git-prefix-
   mangled into `C:/Program Files/Git/backup/...` before kubectl sees them.
3. With that guard set (`MSYS_NO_PATHCONV=1`), a `--kubeconfig $TEMP/...` argument dies
   (`GetFileAttributesEx /tmp/kubeconfig`): THIS bash exports `TEMP=/tmp`, and MSYS had
   been silently converting the kubeconfig path all along. The pair is only safe as
   `KUBECONFIG='<C:/...>'` env + `MSYS_NO_PATHCONV=1` — refining the standing rule.
Working recipe: env-var kubeconfig + `MSYS_NO_PATHCONV=1 kubectl exec … -- sh -c
'base64 /backup/…'` (whole-string `sh -c` args are conversion-immune) → `base64 -d` on
host. Operational miss recorded: deleting the fixture pod in the same command as a
failed copy destroyed the archive once; re-created via the idempotent fixture — and an
apply onto a *terminating* pod yields a new pod whose logs are not the old pod's
(stale `28c4c78b…` vs fresh `ce5a41c5…` hash confusion).

**A3 — proof.** Archive 232 B; local sha256 `ce5a41c54201bfb8849bd0fde81c6167b69e14cbb3367ad2ce48557f22cc0e8b`
== in-pod `SHA256SUMS` ✔; `tar -tzf` intact (raw-media/events/g8-edge-put-….bin).
Backup inventory: `nagardb.sql` 22,846 B + `raw-media-backup.tar.gz` 232 B.
Fixture pod deleted after proof; fixture manifest kept (per G8 doctrine) for closeout
teardown.

### Phase B — host-level clean (no cluster impact)

Guard order honored: live-state snapshot → prune → re-verify, volumes never listed for
pruning. Before/after `docker system df` (identical except Build Cache):

    BEFORE: Images 3/428.1MB · Containers 3/2.187MB · Volumes 6/71.29GB (all active)
            Build Cache 223 entries / 25.72GB (100% reclaimable)
    ops:    docker builder prune -af → "Total: 25.72GB" (223→0 entries)
            docker image prune -f (dangling only) → 0B
            docker container prune -f (exited only)  → 0B
    AFTER:  Images/Containers/Volumes byte-identical · Build Cache 0B

Cluster continuity proof: all three k3d containers `Up` on both sides of the prune
(server-0, serverlb, registry), 6/6 volumes preserved, and post-prune Kubernetes state
unchanged — **15/15 Argo Applications Synced/Healthy**. Docker-side residue is now zero;
the remaining bulk (45 GB containerd store + 21.2 GB registry payload inside the 71.29 GB
of volume state) belongs to phases C–D: registry tag-prune + GC, then the destructive
rebuild with project-named volumes, VHDX compaction, and hygiene automation.

### Phase C — internal registry tag-prune + garbage-collect (evidence-first)

Target: `k3d-nagar.localhost` (registry:2), payload volume
`8812c59388f104f3856fd8f827ad9e9f9082b5ba3721d42d5aa8373f912c9b5f` at /var/lib/registry,
**before-size 21.2 GB** (in-container `du -sh`). Catalog: **24 repositories, 103 tags**
(bulk: `git-repo-mirror` × 69 phase tags; per-service superseded chains:
admin ×5, ingestion ×3, schema-indexer ×3, query/slm/frontend ×2 each).

Source of truth: `deploy/phases/*/digest-pins/kustomization.yaml` — **33 distinct
sha256 digests referenced by git**, of which **21 resolve to a live tag in this
registry**; 12 are superseded older pins (past mirror/schema-indexer/ingestion/
frontend tags) with no surviving tag — recorded, left alone. Pre-delete computation
ran read-only (curl `--noproxy '*'` — Python-spawned curl stalls through the Windows
proxy without it; second Windows-specific lesson of this phase) and wrote the full
map to `agentic/phase-c-tagmap.txt` (103 rows: 21 `KEEP-PIN`, 82 `DELETE`, digest per
tag — the delete set is reconstructable from these rows; the computation/deletion
scripts were one-shot tools, kept out of the tree at the deletion-first pass). Sanity
gates before any deletion: the 21 pinned repo:tag
rows all carry the exact digests from git; zero pinned digest appears in the delete
set; manifest-body media-type probe found no multi-arch index riding a to-delete tag,
so no protected children. Full per-tag map preserved in-tree for reconstructability;
summary:

    KEEP-PIN  (21) — one current tag per mission repo, digest == git pin, e.g.
      mission/busybox:day0, mission/cnpg-operator:1.30.1, mission/cnpg-postgresql:15.17-system-trixie,
      mission/minio:phase3, mission/minio-mc:phase3, mission/redis:phase3,
      mission/strimzi-{operator,kafka}:1.2.0(-kafka-4.2.0), mission/qdrant:v1.15.1,
      mission/ollama:0.12.6, mission/ollama-models:phase6-1, mission/schema-indexer:phase6-3,
      mission/traefik:v3.5, mission/nagar-{auth,query,slm,admin,enrich-worker,frontend,vault-ui,ingestion}:current
    DELETE    (82) — every superseded tag whose manifest digest is NOT git-referenced,
      incl. git-repo-mirror:phase2..phase8-14 (68), admin phase7f-1..4, ingestion
      phase7e-1..2, schema-indexer phase6-1..2, query phase7b-1, slm phase7d-1,
      frontend phase7g-1

**Execution (gated, abort-on-error).** Live registry stopped (`docker stop
k3d-nagar.localhost` → `exited`), one-shot `nagar-registry-gc` (registry:2,
`REGISTRY_STORAGE_DELETE_ENABLED=true`) mounted the SAME volume, catalog re-verified
(24 repos, 200) before any delete. All 82 planned tags deleted by digest:
**82/82 accepted (202), 0 errors, 0 already-gone**. Post-delete tag inventory equals
the committed KEEP rows exactly (21 tagged manifests; the three digest-referenced
repos — git-repo-mirror, postgres-15-alpine, python-builder — keep their manifests
with tags unlinked, which is all k3s's digest-based mirror pulls need).
Garbage-collect: dry-run enumerated 96 eligible blobs → real GC deleted them →
**after-size 21.1 GB, 676 blobs** (22,638,365,576 B).

**Estimate miss, documented honestly:** the plan projected 21.2 → 5–8 GB; reality is
21.2 → 21.1 GB. The deletion set was exactly right (82/82, zero pinned touched); the
size model was wrong. Payload anatomy after GC: the two largest blobs are ~2.24 GB and
~1.82 GB (pinned ollama-models / strimzi-kafka class layers), then a ladder of ~117 MB
identical-size shared base layers — the 69 old mirror tags and superseded service tags
were near-total layer-sharers, so their manifests' deletion freed only 96 blobs
(tiny config/manifest layers), while **the surviving ~21 GB IS the pinned current
image set itself**. Conclusion for the VHDX goal: registry surgery removes
reconstructable history but not the working set; the real byte lever is Phase D
(cluster rebuild wipes the 45 GB containerd store) plus compaction, not more registry
work. Nothing further to prune without deleting pinned images.

**Continuity proof (after `docker start k3d-nagar.localhost`):** catalog HTTP 200 with
24 repositories; **21/21 pinned digests HEAD-resolve to their exact git-pinned digests**
(PASS=21 FAIL=0; first attempt reported 63 fake "passes" from a broken `rev`-based
bash loop plus CRLF map rows — redone in Python for a trustworthy result; an earlier
PASS=0 run was my own URL bug, full ref in the repo path position, fixed and rerun);
Argo **15/15 Applications Synced/Healthy**. One-shot GC container removed; live
registry restored to service. No volume pruned, no Phase D work performed.

### Phase D — destructive rebuild with project-named volumes (all gates green)

Goal state reached: the 45 GB containerd store and the five hex anonymous volumes are
gone; every surviving volume is project-named; the pruned 21.1 GB pinned registry
payload lives in `nagar-registry-data`.

**Sequence, each step gated on the previous proof:**
1. Baseline: 6 volumes / 71.17 GB, cluster healthy, 15/15 Argo (pre-rebuild).
2. Pre-created the six named volumes (`k3d-nagar-server-0-{k3s,kubelet,cni,logs,images}`,
   `nagar-registry-data`).
3. Registry payload copy old→new in one container with both mounts (`cp -a`, src :ro),
   behind a `docker stop k3d-nagar.localhost` write fence: **1,473 files == 1,473
   files; 22,638,365,576 B vs 22,638,386,056 B** (+20,480 B = five 4 KiB directory-entry
   artifacts, zero data-file difference). MSYS guard `MSYS_NO_PATHCONV=1` now required
   for `docker run … sh -c` too (first attempt had `/from` rewritten to
   `C:/Program Files/Git/from` — same trap family, new command surface).
4. Copy proven AS A REGISTRY: two temp `registry:2` instances (old volume :35100, copy
   :35101) → catalogs identical (24 repos), tag sets identical (21 tags), and
   **21/21 pinned digests src == dst == git**.
5. `k3d cluster delete nagar` → containers gone; `k3d registry delete nagar.localhost`
   → payload survived (its content is in my copied named volume, not the deleted
   container). **Finding: k3d's delete removed the five hex anonymous volumes itself**
   — they were k3d-managed cluster volumes, not orphans; formal `volume inspect`
   proof recorded for all five IDs.
6. Registry recreated on the named volume (`k3d registry create nagar.localhost
   --port 35000 -v nagar-registry-data:/var/lib/registry`) → catalog 200/24 repos.
7. Cluster recreated per the G0 recipe (same image, `--registry-use
   nagar.localhost:35000`, `C:/...` storage bind, `--disable=traefik@server:0`) plus
   four named-volume binds (`k3s`, `kubelet`, `cni`, `logs`).

**Two debug episodes (systematic, both recorded):**
- Create attempt #1 failed ("No nodes found" during k3d's pre-create cleanup): the
  stale `k3d-nagar` docker NETWORK had survived both deletes — the registry container
  kept it alive by attachment. `docker network disconnect` + `network rm` cleared it;
  registry stayed healthy (catalog 200).
- Attempt #2 failed again; the first two runs were judged from `tail -3` (rollback
  lines only — self-inflicted blindness). Full log capture exposed the real error:
  **"Duplicate mount point: /k3d/images"** — k3d manages `/k3d/images` itself and
  auto-creates its own project-named `k3d-nagar-images` volume; my explicit `-images`
  bind collided. Lesson restated: never diagnose from a truncated tail; capture the
  whole log. Attempt #3 (without the `-images` bind) → `Cluster 'nagar' created
  successfully!`.

**Continuity proof on the rebuilt substrate:** kubeconfig regenerated
(host.docker.internal→127.0.0.1), **new API port 62398** (recorded; was 57306);
`node/k3d-nagar-server-0` Ready on a **fresh containerd store of 246 MB** (was 45 GB);
registry catalog 200 with 24 repositories; **21/21 pinned digests HEAD-match their
git digests**; server-0 mounts verified as the four named volumes + `k3d-nagar-images`
+ the storage bind. Argo is absent on the fresh cluster (`applications` resource
unknown) — **expected pre-Phase-E**, not a failure.

**Cleanup of superseded volumes (gated, by ID):** all five hex IDs proven gone
(via k3d delete, step 5); my now-redundant empty `k3d-nagar-server-0-images` removed
BY ID (k3d owns the images volume). **No blind `docker volume prune` was ever run.**

**Final state:** volumes 6/6 project-named — `k3d-nagar-images`,
`k3d-nagar-server-0-{cni,k3s,kubelet,logs}`, `nagar-registry-data`;
`docker system df`: Images 4/460 MB, Containers 4/1.987 MB, **Local Volumes 22.89 GB
(was 71.17 GB — −48.3 GB)**, Build Cache 0; containerd store 246 MB; registry payload
21.1 GB (the pinned working set, proven). Containers: `k3d-nagar-server-0`,
`k3d-nagar-serverlb`, `k3d-nagar.localhost`, `k3d-nagar-tools` (k3d's helper node).
Next per plan: Phase E — Argo bootstrap re-apply, 15-app resync from git, admin8
re-seed; then the one-time VHDX compaction and the weekly hygiene automation.

### Phase E — bootstrap the rebuilt substrate from git; secrets resealed; platform green

**Bootstrap source:** OPERATIONS §2/§3 + the §12.20 replay recipe (mission-log "bootstrap
is one SSA of the phase tree"). Discovery: on a virgin cluster `02-gitops` cannot land
first (no namespaces) — the true order is **phase-1 tree first** (namespaces, Kyverno,
cert-manager, sealed-secrets controller), then `02-gitops`. Both builds gated green
before apply (126 + 75 docs); CRD-ordering churn on the first 01-apply was resolved by
the sanctioned re-apply after `crd Established` (idempotent by design). Applications
sync from the in-cluster git mirror at `phase8-15` == local HEAD for deploy/ manifests.

**The Sealed Secrets wall (found before it failed the platform):** the rebuild gave the
controller a NEW keypair, and G1.2's notes record the old private key as **ephemeral by
design** (shredded post-drill) — the five old sealed blobs were mathematically dead.
Executed OPERATIONS §4 (one-time per cluster): fresh values generated in shell, never
displayed; all five blobs resealed offline with kubeseal 0.28.0 against the new
controller cert (10-yr keypair, extracted from `sealed-secrets-keyjvwxv` after my
guessed name 404'd); data-key shapes byte-compared to the old files; ADR-011 ¶5
honored (one `nagar` password pinned identically into `databaseUrl` and the bootstrap
basic-auth secret); MinIO keys shared across `nagar-minio`/`nagar-minio-server`
including the `MC_HOST_local` URL form. Committed `d02b0094` and shipped via the
mirror cycle (tag `phase8-16`; two build-gated failures recorded: the payload must be
`payload/nagarvault.git` beside `git-mirror/Dockerfile`, context = `git-mirror/`).
**Landing split, git-evidenced:** the `nagar-platform` pair rides its phase trees via
Argo (controller log: "Unsealed successfully" ×2); the `nagar-app` trio lands via the
G1.2 bootstrap ritual `kubectl apply -f deploy/phases/01-substrate/secrets/` (the
directory is referenced by no kustomization — matches G1.2 line 276 verbatim).

**Timing finding:** the 15 Applications synced the PRE-reseal mirror revision first;
secret-consuming pods sat in CreateContainerConfigError (correct fail-closed) until
the resealed trio landed, then Kubernetes/Argo self-healed to 14/14 Running — the only
live actions were the sanctioned ritual apply and pod deletes of Deployment-owned
pods. `nagar-db-migrate` ran clean against the fresh `nagardb` (DDL + officer roles).

**Idempotent Jobs end-state:** `bucket-init` Complete (buckets recreated),
`nagar-kafka-topics` Complete, `nagar-db-migrate` Complete, `nagar-ollama-models`
Complete (models re-copied), and `nagar-schema-index` — **Failed then fixed**: the Job
has no dependency wait, launched while ollama was still creating, exhausted backoff
before deps were up (pods garbage-collected, logs lost; evidence from Job conditions
+ events). Sanctioned re-run per OPERATIONS §8 (delete Job → Argo recreates):
`INDEX-SYNC-OK — 40 documents, 40 points, dim=1024` (re-embed gate met; the one
dependency-probe refusal in its log is the recorded race, retried by the Job itself).

**Proofs (Phase E gates):** node `k3d-nagar-server-0` Ready; **15/15 Applications
Synced/Healthy**; admin re-seeded via the sanctioned OPERATIONS §5 ritual
(`seed_admin.py --username admin8 --user-id admin8-001 --password …`, stdout
discarded, password never displayed — idempotent re-run safe); edge proof through the
rebuilt stack: `POST /auth/login → 200`, `whoami → role: admin` (cookie jar shredded,
port-forward killed). Remaining from the master plan: VHDX compaction (Phase F) and
the weekly hygiene automation (Phase G).

### Phase F — VHDX compaction (diskpart fallback; a repair lesson recorded)

`docker_data.vhdx` **123,692,122,112 B (123.7 GB) → 46,125,809,664 B (46.1 GB) —
≈ 77.6 GB reclaimed on the host disk.** Optimize-VHD is absent on this Windows edition
(Hyper-V module), so the diskpart fallback ran (attach readonly → compact vdisk →
detach), elevated via the sanctioned prompt (script in git history at
`agentic/ops/phase-f-compact.ps1`; log at `%TEMP%\phase-f-compaction.log`). Compact
itself: clean (progress to 100%, detach
successful).

**The failure the script's own death caused, and the systematic repair:** the elevated
PowerShell process was torn down the moment diskpart returned, so the script's restart
step and done-marker never ran — and, critically, **the VHDX was left ATTACHED**. Docker
Desktop then failed to boot with `wsl-bootstrap … detecting disk: no sd* disk in
/sys/block with wwid ending adf0f0c03179…` and a sibling
`AttachDisk/MountDisk/HCS/ERROR_SHARING_VIOLATION`. Systematic read of the backend logs
showed the WWID line was the downstream symptom: WSL could not attach the disk at all
(sharing violation — my leftover host attachment), so the in-VM bootstrap never saw
its device. A repair pass (elevated diskpart detach; script in git history at
`agentic/ops/phase-f-repair.ps1`) detached the
orphaned attachment (and proved along the way that the data VHDX is a raw unpartitioned
disk — no GPT DiskId exists to restore, so the "identity regenerated" theory was
falsified); a clean Docker Desktop restart after that came up healthy. Two lessons in
the ledger: (1) never diagnose from a truncated log tail — the WWID error was a decoy;
(2) long-running elevated scripts must be resilient to process teardown: the script
that leaves the machine in a *valid* state before its slowest step, not after.

**Return-to-service proof:** engine up, k3d containers back (`k3d-nagar-tools` needed
one `docker start` — it had been killed mid-flight), node Ready, **48 pods
Running/Completed with zero failures**, Argo **15/15 Synced/Healthy**, registry catalog
200/24 repos, **21/21 pinned digests HEAD-verified** (one earlier spot-check MISMATCH
was a cold-start empty response, superseded by the full warm check).

### Phase G — weekly Docker hygiene automation

`agentic/ops/docker-hygiene.ps1` — safe by construction: prunes build cache older than
7 days, dangling images, and exited NON-k3d containers; **never touches volumes** (the
k3d mission state lives exclusively there); starts Docker Desktop if the engine is down
and aborts the run if it does not come up; before/after `docker system df` into
`%TEMP%\docker-hygiene.log`. Test-run verified live (one stale cache record pruned,
volumes byte-identical, k3d containers respected). Registered as scheduled task
**"NagarVault Docker Hygiene"** (Sundays 03:00, `StartWhenAvailable` so a powered-off
host catches up): state=Ready, next run 2026-10-04 03:00. Residual reclaimable at
registration time: build cache 123.7 MB (aging out weekly), dangling 0 B.

### Mission outcome — storage optimization complete (all phases)

| Metric | Before | After |
|---|---|---|
| docker_data.vhdx on host disk | 123.7 GB | **46.1 GB (−77.6 GB)** |
| Docker-visible volume bytes | 71.29 GB (5 hex + 1 named) | 40.7 GB (6 project-named) |
| k3s containerd store | 45 GB (60+ stale tags) | 246 MB fresh → ~17 GB after mission re-pull (current digests only) |
| Registry payload | 21.2 GB (103 tags) | 21.1 GB (21 tagged manifests, digest-referenced only) |
| Build cache | 25.72 GB | ~0.65 GB warm working set (auto-aged weekly) |
| Volume naming | 5 anonymous hex + 1 k3d | 6/6 project-named |
| Live state | — | Argo 15/15 Synced/Healthy; edge login proven; sealed secrets re-issued |

Every deleted byte was either reclaimable cache, unreferenced tag history, or a stale
containerd layer; the pinned working set, all live PVC data (backed up in Phase A
before any destructive step), and the sealed-secret identities were preserved or
re-issued through sanctioned procedures. The Phase-A backup was never needed. Git
commits this mission: `b0e64464`, `c1d88027`, `c26670ca`, `f4533e30`, `6635c932`,
`d02b0094`, `237ccc2b`, plus this log update; **nothing pushed**.

### SUBSTRATE.md audit response (2026-10-01)

Post-publication audit of `docs/SUBSTRATE.md` (`bc94df9b`) ran the §2.2 recipe
verbatim (read-only) against the live registry and found the keep-set rule **one
source short**: derive-list = 1, containing `mission/git-repo-mirror:phase8-16` —
the mirror transport referenced by `newTag:` in git-mirror/kustomization.yaml, which
digest pins do NOT cover; a reader following the doc would have deleted the tag the
cluster's git sync depends on. Fixed in docs only: keep-set rule now has two sources
(digest pins + the `newTag`-resolved mirror transport digest, with a bold warning),
the delete-list review step forbids the mirror tag, and §3.1 now leads with the
generic `docker inspect` volume lookup (dead pre-rebuild hex ID demoted). Also
corrected the OPERATIONS §12 anchor to the real GitHub slug
(`#12-troubleshooting-matrix-symptom--cause--fix` — the heading's `→` becomes a
double hyphen) and reframed §7 as "traps OPERATIONS §12 does not cover".
Verification: corrected rule re-run read-only → keep set 34 (33 pins + mirror
digest), **delete list = 0** on the live registry; programmatic anchor check →
`BAD TOTAL: 0`; no live state mutated, no digest pin added in-cluster.

---

## G8 — six-gate E2E re-run on the rebuilt substrate (2026-10-01, k3d substrate)

Step 4 of the Phase-8 plan requires all six E2E gates against the live edge with real command
output recorded below. The gates were first run on 2026-09-30 (G8.1–G8.7 above); the substrate was
then **destroyed and rebuilt from git** in the storage-optimization pass (Phases A–G), so this
section re-executes all six against the rebuilt cluster — same gates, fresh evidence — and
corrects one instrument artifact in the original G8.1 record.

Entry state: **15/15 Applications Synced/Healthy**; Traefik edge `1/1` on
`mission/traefik@sha256:e157892e…`; the host has no 80/443 mapping, so every gate ran through an
**inline `kubectl port-forward svc/traefik-edge 8443:443`** (spawn → prove with a `/auth/` 200 →
run → kill; no forward outlived its gate). Kubeconfig `C:/Users/styli/AppData/Local/Temp/kubeconfig`
— the brief's 127.0.0.1:57306 is the pre-rebuild port; the live server is **127.0.0.1:62398**.
Substrate event handled before the gates: Docker Desktop was down after a host restart; the engine
was started and orphaned `kubectl.exe` listeners cleared first, after which the cluster
self-healed to 15/15 with zero manual workload changes. `--kubeconfig` was used bare; the two
in-pod staging pipes used `KUBECONFIG=<C:/…> MSYS_NO_PATHCONV=1 kubectl …` (the never-combine rule).

### G8R.1 — TLS: leaf chains to the internal CA (re-proven)

CA re-extracted from `cert-manager/nagar-edge-ca-keypair` (562 B):

    $ openssl x509 -in /tmp/nagar-edge-ca.pem -noout -subject -issuer -dates
    subject=CN=nagar-edge-ca
    issuer=CN=nagar-edge-ca
    notBefore=Sep 30 19:24:53 2026 GMT
    notAfter=Sep 30 19:24:53 2027 GMT

    $ openssl s_client -connect 127.0.0.1:8443 -servername k3d.nagar.internal \
        -CAfile /tmp/nagar-edge-ca.pem -verify_return_error
    depth=1 CN=nagar-edge-ca
    depth=0 CN=k3d.nagar.internal
    subject=CN=k3d.nagar.internal
    issuer=CN=nagar-edge-ca
    Verify return code: 0 (ok)

    $ openssl s_client … </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
    subject=CN=k3d.nagar.internal
    issuer=CN=nagar-edge-ca
    notBefore=Sep 30 19:24:57 2026 GMT
    notAfter=Dec 29 19:24:57 2026 GMT
    X509v3 Subject Alternative Name:
        DNS:k3d.nagar.internal, DNS:k3d-nagar.localhost

**Protocol-floor correction (honest record fix).** The original G8.1 recorded “TLS-1.1-only
handshake → 000 (handshake refused)” as if the *server* refused. Re-run today shows that was an
**instrument artifact**: every client available here refuses to even attempt TLS ≤1.1
client-side —

    $ curl -sk --ssl-no-revoke --tls-max 1.1 …        # curl 8.21.0/Schannel
    curl --tls-max 1.1 exit=35
    $ curl -sk --ssl-no-revoke --tls-max 1.2 …        → http=200
    $ openssl s_client -tls1_1 … (host OpenSSL 3.5.7)
    189B0000:error:0A0000BF:SSL routines:tls_setup_handshake:no protocols available
    $ MSYS_NO_PATHCONV=1 KUBECONFIG=… kubectl -n nagar-platform exec nagar-dual-role-0 -- sh -c \
        'openssl version; echo | openssl s_client -tls1_1 -connect traefik-edge…:443 -servername k3d.nagar.internal'
    OpenSSL 3.5.5 27 Jan 2026 … → no protocols available

Node’s bundled OpenSSL refuses identically (`ERR_SSL_NO_PROTOCOLS_AVAILABLE`). What **is**
observable: TLS 1.2-only and 1.3 handshakes succeed on the valid SNI, and both route namespaces
carry the deployed TLSOption:

    $ kubectl get tlsoption -A
    nagar-app        edge-tls-options   VersionTLS12   true
    nagar-platform   edge-tls-options   VersionTLS12   true

So the floor stands as *declared configuration* (`minVersion: VersionTLS12`) plus positive
negotiation evidence; the negative ≤1.1 probe is **not constructible in this environment**, and the
original “000” line must not be read as a server-side refusal in future reviews. (Side note, not a
defect: no-SNI and bogus-SNI handshakes get Traefik's default self-signed fallback cert — that is
the no-router-matches fallback, so it is not evidence either way about the matched routers'
`sniStrict`.)

### G8R.2 — CORS: exactly the deployed middleware, allow + deny

Deployed middleware read before probing:

    $ kubectl -n nagar-platform get middleware edge-cors -o yaml
    spec:
      headers:
        accessControlAllowCredentials: true
        accessControlAllowHeaders:
        - Content-Type
        - Authorization
        - x-amz-date
        - x-amz-content-sha256
        - Range
        accessControlAllowMethods:
        - GET
        - PUT
        - POST
        - HEAD
        - OPTIONS
        accessControlAllowOriginListRegex:
        - https://(k3d\.nagar\.internal|k3d-nagar\.localhost)
        accessControlMaxAge: 600

Preflight, allowed origin:

    $ curl -sk -i -X OPTIONS -H 'Origin: https://k3d-nagar.localhost' \
        -H 'Access-Control-Request-Method: PUT' -H 'Access-Control-Request-Headers: content-type' \
        https://k3d.nagar.internal:8443/minio/raw-media/g8-cors-probe.bin
    HTTP/1.1 200 OK
    Access-Control-Allow-Credentials: true
    Access-Control-Allow-Headers: Content-Type,Authorization,x-amz-date,x-amz-content-sha256,Range
    Access-Control-Allow-Methods: GET,PUT,POST,HEAD,OPTIONS
    Access-Control-Allow-Origin: https://k3d-nagar.localhost
    Access-Control-Max-Age: 600
    Content-Length: 0
    Strict-Transport-Security: max-age=31536000; includeSubDomains
    X-Content-Type-Options: nosniff
    X-Frame-Options: DENY
    X-Xss-Protection: 1; mode=block

Preflight, disallowed origin — no ACAO (the browser-enforced negative; Traefik answers the
preflight without an allow-origin so the client blocks it):

    $ … -H 'Origin: https://evil.example.com' …
    HTTP/1.1 200 OK
    Access-Control-Allow-Credentials: true
    Access-Control-Allow-Headers: Content-Type,Authorization,x-amz-date,x-amz-content-sha256,Range
    Access-Control-Allow-Methods: GET,PUT,POST,HEAD,OPTIONS
    Access-Control-Max-Age: 600
    Content-Length: 0
    # NO Access-Control-Allow-Origin, NO Vary

Non-preflight GET with allowed origin — CORS + security headers compose on one router:

    HTTP/1.1 403 Forbidden            # MinIO: probe object does not exist
    Access-Control-Allow-Credentials: true
    Access-Control-Allow-Origin: https://k3d-nagar.localhost
    Access-Control-Expose-Headers: Date, Etag, Server, … X-Amz*, *
    Vary: Origin                      # addVaryHeader
    Strict-Transport-Security: max-age=31536000; includeSubDomains

### G8R.3 — Rate limit: 429 attributable to Traefik, not uvicorn

32 sequential `POST /auth/login` (wrong credentials) through the edge, after 2 legitimate logins
(the G8R.5 prep) had warmed the same buckets:

    req 1 -> 401 retry-after=<none> body={"detail":"invalid credentials"}
    req 2 -> 401 retry-after=<none> body={"detail":"invalid credentials"}
    req 3 -> 401 retry-after=<none> body={"detail":"invalid credentials"}
    req 4 -> 401 retry-after=<none> body={"detail":"invalid credentials"}
    req 5 -> 401 retry-after=<none> body={"detail":"invalid credentials"}
    req 6 -> 401 retry-after=<none> body={"detail":"invalid credentials"}
    req 7 -> 401 retry-after=<none> body={"detail":"invalid credentials"}
    req 8 -> 429 retry-after=<none> body={"detail":"login rate limit exceeded"}
    req 9 -> 401 retry-after=<none> body={"detail":"invalid credentials"}
    req 10 -> 429 retry-after=<none> body={"detail":"login rate limit exceeded"}
    req 11 -> 429 retry-after=<none> body={"detail":"login rate limit exceeded"}
    req 12 -> 429 retry-after=<none> body={"detail":"login rate limit exceeded"}
    req 13 -> 429 retry-after=<none> body={"detail":"login rate limit exceeded"}
    req 14 -> 429 retry-after=<none> body={"detail":"login rate limit exceeded"}
    req 15 -> 429 retry-after=<none> body={"detail":"login rate limit exceeded"}
    req 16 -> 429 retry-after=<none> body={"detail":"login rate limit exceeded"}
    req 17 -> 429 retry-after=<none> body={"detail":"login rate limit exceeded"}
    req 18 -> 429 retry-after=1 body=Too Many Requests
    req 19 -> 429 retry-after=<none> body={"detail":"login rate limit exceeded"}
    req 20 -> 429 retry-after=6 body=Too Many Requests
    req 21 -> 429 retry-after=6 body=Too Many Requests
    req 22 -> 429 retry-after=6 body=Too Many Requests
    req 23 -> 429 retry-after=5 body=Too Many Requests
    req 24 -> 429 retry-after=5 body=Too Many Requests
    req 25 -> 429 retry-after=5 body=Too Many Requests
    req 26 -> 429 retry-after=4 body=Too Many Requests
    req 27 -> 429 retry-after=4 body=Too Many Requests
    req 28 -> 429 retry-after=4 body=Too Many Requests
    req 29 -> 429 retry-after=3 body=Too Many Requests
    req 30 -> 429 retry-after=3 body=Too Many Requests
    req 31 -> 429 retry-after=3 body=Too Many Requests
    req 32 -> 429 retry-after=2 body=Too Many Requests

    ---- full 33rd response (headers) ----
    HTTP/1.1 429 Too Many Requests
    Retry-After: 2
    Strict-Transport-Security: max-age=31536000; includeSubDomains
    X-Content-Type-Options: nosniff
    X-Frame-Options: DENY
    X-Retry-In: 1.463835704s
    X-Xss-Protection: 1; mode=block
    Date: Thu, 01 Oct 2026 17:36:21 GMT
    Content-Length: 17

    Too Many Requests

Attribution is byte-level: the app's limiter answers `429 {"detail":"login rate limit exceeded"}`
(FastAPI JSON, no Retry-After); Traefik's `edge-ratelimit` (average 10 / burst 20 / 1m on the whole
`/auth` router — `ingressroutes.yaml`) answers plain-text `Too Many Requests` with `Retry-After`
and `X-Retry-In`. Shape: req 1–7 pass (401), 8 hits the app limiter, 9 passes as a per-pod deque
slot frees, 10–17 app limiter, 18 the edge bucket, 19 one more app slot, 20–32 all edge, counting
recovery down 6→2. Same conclusion as G8.3: the in-app limiter is per-pod (2 replicas), the edge
bucket is the only global control.

### G8R.4 — Presigned PUT through the edge: bytes verified in MinIO

7e contract (`app.js` header): `POST /api/v1/uploads/presign   JWT; mint presigned PUTs + store
intents (TTL 600s)`; ADR-024 §6: `/minio` is the browser presigned-PUT route and `edge-cors`
lives only there.

    $ POST /api/v1/uploads/presign (admin Bearer, via edge /api)
    {"uploads":[{"attachmentId":"65875e02-2325-4266-8ead-7145e38d23a3","bucket":"raw-media",
     "objectKey":"events/65875e02-2325-4266-8ead-7145e38d23a3/g8-edge-put3.bin",
     "url":"http://minio.nagar-platform.svc.cluster.local:9000/raw-media/events/65875e02-2325-4266-8ead-7145e38d23a3/g8-edge-put3.bin?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Content-Sha256=UNSIGNED-PAYLOAD&X-Amz-Credential=<masked>&X-Amz-Date=20261001T173907Z&X-Amz-Expires=300&X-Amz-Signature=<masked>&X-Amz-SignedHeaders=host&x-amz-checksum-crc32=AAAAAA%3D%3D&x-amz-sdk-checksum-algorithm=CRC32&x-id=PutObject"}],
     "ttlSeconds":600}

**Discrepancy re-confirmed (same as G8.4):** the minted URL host is cluster-internal DNS
(`minio.nagar-platform.svc.cluster.local:9000`) — 7e's presigner reads only `MINIO_URL`
(`runtime.js`), there is **no external-host env**, so the literal browser flow cannot be exercised
end-to-end. Proven instead by the **equivalent path**: an edge-origin URL minted inside the
ingestion pod with its own SDK + secret env (credentials never left the pod; masked on display):

    https://k3d.nagar.internal:8443/raw-media/events/65875e02-2325-4266-8ead-7145e38d23a3/g8-edge-put3.bin?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Content-Sha256=UNS
    (masked output as captured, first 160 chars)
    # browser-adapter path rewrite: insert the /minio routing prefix; the signature was computed
    # over the MinIO-native path, and the edge strip delivers exactly that path to MinIO

    $ PUT through the edge /minio route (62 random bytes)
    HTTP/1.1 200 OK
    Content-Length: 0
    Etag: "346376aac8e07bb1d2cd0dd923b48492"
    Server: MinIO
    Vary: Origin

    # verify from the ingestion pod: HeadObject + GetObject sha256
    {"size":62,"etag":"\"346376aac8e07bb1d2cd0dd923b48492\"","bytes_read":62,
     "sha256":"3b73916107689583b561e07df525f8ab997fa30477947ef75a4f9f49bc3f3799"}
    SHA256-MATCH: object byte-intact in MinIO
    MD5/ETAG-MATCH: 346376aac8e07bb1d2cd0dd923b48492

Instrument notes (both cost a cycle, recorded): (1) `NODE_PATH` does **not** apply to ESM
`import` — the first mint used a `.mjs` script and died `ERR_MODULE_NOT_FOUND`; `require()` in a
`.cjs` script is the working pattern in this read-only-root pod. (2) The pod's SDK defaults to
CRC32 integrity checks and the API-minted URL carries `x-amz-checksum-crc32=AAAAAA==` (the
empty-body checksum); the edge-path mint set `requestChecksumCalculation: "WHEN_REQUIRED"` for a
clean PUT — the API-minted URL's usability is unchanged from 7e's own E2E record and is not
re-litigated here.

### G8R.5 — Authz negatives at the edge (401 / 403); officer seeded via the 7a ritual

Officer created through the admin-gated `POST /auth/create`, never `seed_admin`; secrets never
displayed:

    $ kubectl -n nagar-app exec deploy/auth-service -- python seed_admin.py --username admin8g8 --user-id admin8g8-001
    ADMIN PASSWORD (record in the operator vault; shown once):   ← value captured to a shell variable (redacted)
    $ POST /auth/login (admin8g8)                      -> {"status":"ok","role":"admin"} HTTP:200
    $ POST /auth/create (admin Bearer)                 -> {"status":"ok","user_id":"officer8g8-188bddcc",
                                                            "username":"officer8g8","role":"nmc_officer"} HTTP:200
    $ POST /auth/login (officer8g8)                    -> {"status":"ok","role":"nmc_officer"} HTTP:200

    $ GET /auth/whoami (officer)                       -> {"sub":"officer8g8-188bddcc","role":"nmc_officer", …}
    $ GET /admin/health/cluster, NO JWT                -> HTTP 401 {"detail":"missing session"}
    $ GET /admin/health/cluster, OFFICER JWT           -> HTTP 403 {"detail":"admin role required"}
    $ GET /admin/dlq?limit=1,          OFFICER JWT     -> HTTP 403 {"detail":"admin role required"}
    $ GET /admin/audit-logs?limit=1,   OFFICER JWT     -> HTTP 403 {"detail":"admin role required"}
    $ GET /admin/health/cluster, ADMIN JWT (contrast)  -> HTTP 200 {"db":true,"kafka":true,"schemaIndexer":true,"all":true}

### G8R.6 — In-cluster flows unaffected by the edge (no StripPrefix regression)

    # BFF-native path, executed inside a frontend pod (never touches the edge):
    $ … kubectl -n nagar-app exec -i deploy/frontend -- sh -c '… node /tmp/g8-incluster.cjs'
    in-cluster whoami status: 200
    {"sub":"admin8g8-001","role":"admin","jti":"<redacted>","exp":…}

    # edge /api is VERBATIM (ingestion's native contract, prefix not stripped)
    $ GET /api/v1/events/evt-g8-nonexistent (admin Bearer via edge)
    HTTP/1.1 404 Not Found
    Content-Length: 28
    {"detail":"unknown eventId"}
    # Traefik access-log attribution:
    "GET /api/v1/events/evt-g8-nonexistent HTTP/1.1" 404 28 … "nagar-app-edge-ingestion-…@kubernetescrd" "http://10.42.0.230:3000"

    # edge / catch-all serves the frontend
    $ GET / -> http=307 bytes=4948 redirect=https://k3d.nagar.internal:8443/dashboard

### Cleanup and invariants

- Officer password and admin seed password never displayed; tokens / cookie jars lived only in
  `/tmp` (mode 600) and were deleted after the run; presigned-URL credential + signature masked in
  every shown output. **I-3.**
- The only cluster-side effects outside the gates: the sanctioned §9.1 `seed_admin.py` execution
  (new admin `admin8g8`, recorded here) and ephemeral files in existing pods' `/tmp` (the
  documented 7b/7x E2E pattern). No `kubectl edit/scale/apply` of any workload, no manifest change
  was needed — **I-1/I-9**. Forward cleanup verified: no `kubectl` processes and no listeners on
  8443/8444 after the run.
- Re-running the whole section is safe (**I-2**): a second seed is a no-op, presign intents expire
  in 600 s, and each probe only writes/overwrites its own `/tmp` script.

### Result — 6/6 GREEN on the rebuilt substrate

TLS chain ✓ · CORS allow/deny ✓ · edge-429 attribution ✓ · presigned PUT byte-intact (edge-path
adaptation, browser-host discrepancy recorded) ✓ · 401/403 authz ✓ · in-cluster paths intact ✓.
No platform defect was found; two honest records stand: the G8.1 protocol-floor line is
instrument-confounded and corrected above, and 7e's `PRESIGN_PUBLIC_URL` gap remains the one open
item (already recorded in G8.7).

---

## Phase 8 — G8C: browser presigned-PUT closure (2026-10-01, k3d substrate)

G8R left exactly one open charter deviation: 7e's presigner minted cluster-internal URLs, so Gate 4's
literal browser-origin PUT could only be proven via an equivalent in-pod mint. Reconciliation against
the contracts before touching code: **PHASES.md §2 Phase 8 Exit = “browser presigned PUT works from
the frontend origin”**, ARCHITECTURE §3.2 has the browser PUTting bytes directly with CORS from the
edge middleware, and the Phase-8 ledger itself named `PRESIGN_PUBLIC_URL` as the 7e follow-up. The
docs therefore require edge-reachable URLs — the decision was to implement the follow-up (not to
re-document in-cluster URLs as correct). Recorded as **ADR-025**.

### G8C.1 — implementation (commit `e6aaa2b`, image `phase7e-4`)

- `src/presign-url.js` (new, pure): swaps scheme/host to the public origin and inserts the frozen
  `/minio` route prefix. `runtime.js`: a **second S3 client pointed at `PRESIGN_PUBLIC_URL`** is used
  for signing when set (SigV4 binds the signed host, so the *signer* must target the edge origin);
  `statObject`/health keep the in-cluster `MINIO_URL` client; unset env keeps legacy behavior.
- Manifest: `PRESIGN_PUBLIC_URL: https://k3d.nagar.internal` on the 7e Deployment
  (`PRESIGN_ROUTE_PREFIX` defaults to `/minio`).
- Hermetic suite (host, node 22.23.2, 4 new unit tests):

```
$ cd deploy/phases/07-app-ingestion/ingestion
$ node --test tests/ingestion.test.js tests/presign-url.test.js
1..10
# tests 10
# pass 10
# fail 0
```

  Instrument find caught by the new unit test before any build: Node's `URL.host` setter does not
  clear a previously parsed port, so the first adapter draft minted
  `https://k3d.nagar.internal:9000/...` — fixed by setting `hostname` + `port` explicitly.
- Image build/push and digest pin (registry header read, machine-compared):

```
$ docker build -f deploy/phases/07-app-ingestion/ingestion/Dockerfile \
    -t localhost:35000/mission/nagar-ingestion:phase7e-4 deploy/phases/07-app-ingestion
$ docker push localhost:35000/mission/nagar-ingestion:phase7e-4
phase7e-4: digest: sha256:d8d681f5b823faa59d0fb5a5ebe92cb1e22041fe33793901890b21f8b0494229 size: 856
$ curl --noproxy '*' -sI http://localhost:35000/v2/mission/nagar-ingestion/manifests/phase7e-4 | grep -i docker-content-digest
Docker-Content-Digest: sha256:d8d681f5b823faa59d0fb5a5ebe92cb1e22041fe33793901890b21f8b0494229
```

- Rendered tree + live admission gate:

```
$ kustomize build --load-restrictor LoadRestrictionsNone deploy/phases/07-app-ingestion | grep -E 'image:|PRESIGN'
        - name: PRESIGN_PUBLIC_URL
          value: https://k3d.nagar.internal
        image: k3d-nagar.localhost:5000/mission/nagar-ingestion@sha256:d8d681f5…
$ cat /tmp/p7e-rendered.yaml | MSYS_NO_PATHCONV=1 KUBECONFIG=<kubeconfig> kubectl apply --dry-run=server -f -
serviceaccount/nagar-ingestion configured (server dry run)
service/ingestion configured (server dry run)
deployment.apps/ingestion configured (server dry run)
poddisruptionbudget.policy/ingestion configured (server dry run)
networkpolicy.networking.k8s.io/ingestion configured (server dry run)
```

- 7e's in-cluster E2E driver now re-mints its media PUT with the pod's own SDK when the API returns a
  public URL (that host is intentionally unreachable in-cluster); the browser-path proof is this
  section's Gate 4. Docs updated in the same commit: ADR-025, PHASES Phase-8 entry (deviation
  closed), ARCHITECTURE §3.2 (minting rule), OPERATIONS §12.36 (symptom→fix row).

### G8C.2 — deployment through the mirror cycle (ADR-018 order)

```
$ rm -rf deploy/phases/02-gitops/git-mirror/payload/nagarvault.git && git clone --bare . …
$ git -C …/payload/nagarvault.git log --oneline -1
e6aaa2bf feat(7e): mint browser presigned PUTs on the public edge origin (ADR-025)
$ docker build -t localhost:35000/mission/git-repo-mirror:phase8-17 deploy/phases/02-gitops/git-mirror
$ docker push localhost:35000/mission/git-repo-mirror:phase8-17
phase8-17: digest: sha256:ff2388d0af79bfdcee32d3c2c77a9391885df87ca50ec1781093787a13d04ad3 size: 856
$ kustomize build deploy/phases/02-gitops/git-mirror > /tmp/git-mirror-built.yaml && echo BUILD-OK
BUILD-OK (2 docs)          # build gated before the apply (traps honored)
$ cat /tmp/git-mirror-built.yaml | MSYS_NO_PATHCONV=1 KUBECONFIG=<kubeconfig> kubectl apply \
    --server-side --force-conflicts -f -
service/git-repo-mirror serverside-applied
deployment.apps/git-repo-mirror serverside-applied
$ kubectl -n nagar-system rollout status deploy/git-repo-mirror --timeout=180s
deployment "git-repo-mirror" successfully rolled out
$ kubectl -n nagar-system exec deploy/git-repo-mirror -- sh -c 'git ls-remote git://127.0.0.1:9418/nagarvault.git HEAD'
e6aaa2bf41ee129ad3ab676f5454c320c016629a	HEAD
```

Argo picked the new HEAD on its next reconciliation (~60 s) and rolled 7e:

```
t+20s rev=d02b0094 Synced Healthy
t+40s rev=d02b0094 Synced Healthy
t+60s rev=e6aaa2bf Synced Progressing
t+80s rev=e6aaa2bf Synced Progressing
t+100s rev=e6aaa2bf Synced Healthy
$ kubectl -n nagar-app get deploy ingestion -o jsonpath='{.spec.template.spec.containers[0].image}'
k3d-nagar.localhost:5000/mission/nagar-ingestion@sha256:d8d681f5b823faa59d0fb5a5ebe92cb1e22041fe33793901890b21f8b0494229
$ kubectl -n nagar-app get pods -l app.kubernetes.io/name=nagar-ingestion \
    -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,IMAGEID:.status.containerStatuses[0].imageID
… both pods true / same digest …
$ kubectl -n nagar-app exec deploy/ingestion -- sh -c 'echo $PRESIGN_PUBLIC_URL; … /health'
PRESIGN_PUBLIC_URL=https://k3d.nagar.internal
{"api":true,"minio":true,"kafka":true}
```

### G8C.3 — Gate 4 re-run LITERALLY from the host (raw evidence)

Reach: inline `kubectl -n nagar-system port-forward svc/traefik-edge 443:443` (spawn → prove → run →
kill; the host has no privileged-port restriction, so the **minted URL is used with zero URL
surgery** — only DNS substitution via `--resolve`, the documented §11/§12.34 substrate method).

```
---- 0) seed a fresh admin via the sanctioned §5 ritual (password captured, never displayed) ----
ADMIN PASSWORD (record in the operator vault; shown once):
admin8c login via edge -> {"status":"ok","role":"admin"} HTTP:200
---- 1) POST /api/v1/uploads/presign via edge (/api) ----
{"uploads":[{"attachmentId":"37b8be21-d4cb-46dc-9f23-3b73afc4a02c","bucket":"raw-media",
 "objectKey":"events/37b8be21-d4cb-46dc-9f23-3b73afc4a02c/g8c-browser-put.bin",
 "url":"https://k3d.nagar.internal/minio/raw-media/events/37b8be21-…/g8c-browser-put.bin
   ?X-Amz-Algorithm=AWS4-HMAC-SHA256&…X-Amz-Credential=<masked>&…X-Amz-Signature=<masked>&…"}],
 "ttlSeconds":600}
URL-SHAPE-OK: public edge origin + frozen /minio prefix
  (https://k3d.nagar.internal/minio/raw-media/events/37b8be21-…/g8c-browser-put.bin)
---- 2) browser preflight (OPTIONS) for the exact minted path ----
HTTP/1.1 200 OK
Access-Control-Allow-Credentials: true
Access-Control-Allow-Headers: Content-Type,Authorization,x-amz-date,x-amz-content-sha256,Range
Access-Control-Allow-Methods: GET,PUT,POST,HEAD,OPTIONS
Access-Control-Allow-Origin: https://k3d-nagar.localhost
Access-Control-Max-Age: 600
---- 3) PUT the minted URL VERBATIM (browser Origin) ----
payload 62 bytes sha256=7fcc27e23e02d38742b0e4807d2f70dd5301fbf435f5d1e62c5a2c55870ee497
HTTP/1.1 200 OK
Access-Control-Allow-Credentials: true
Access-Control-Allow-Origin: https://k3d-nagar.localhost
…
Etag: "dbccb5f17b56b59ff4e986b13c1251be"
Server: MinIO
Vary: Origin
---- 4) byte verification in MinIO (in-pod HeadObject + GetObject sha256) ----
{"size":62,"etag":"\"dbccb5f17b56b59ff4e986b13c1251be\"","bytes_read":62,
 "sha256":"7fcc27e23e02d38742b0e4807d2f70dd5301fbf435f5d1e62c5a2c55870ee497"}
SHA256-MATCH: bytes intact in MinIO
MD5/ETAG-MATCH: dbccb5f17b56b59ff4e986b13c1251be
---- 5) commit leg: POST /api/v1/events via edge (statObject must accept the uploaded object) ----
commit -> {"eventId":"evt-14c50754-a255-4a3f-b42f-1df8886fc431",
           "topic":"nmc.complaints.raw.restricted.v1"} HTTP:202
```

Downstream leg (the full §3.2 chain, closing G7e-style): the 7c worker enriched the event —

```
SELECT event_id, media_object_key FROM nmc_complaints WHERE source_system='g8c';
evt-14c50754-a255-4a3f-b42f-1df8886fc431|events/37b8be21-…/g8c-browser-put.bin
DELETE 1
FIXTURE-REMOVED events/37b8be21-…/g8c-browser-put.bin
no leaked 443 listener · kubectl.exe processes: 0
```

### G8C.4 — platform state and invariants

`15/15` Applications Synced/Healthy; `nagar-phase7e-ingestion` at revision `e6aaa2bf` (Synced/
Healthy); both ingestion pods Running on the `phase7e-4` digest. **I-1** — every change reached the
cluster through git → mirror → Argo (transport apply = §9.4); the only live actions were the
sanctioned §9.1 seed and cleanup of our own fixture (row + object), both recorded. **I-2** — the seed
is idempotent; presign intents TTL; the fixture cleanup is a no-op on re-run. **I-3** — passwords
never displayed (captured to shell vars only); presigned credential/signature masked in every shown
output; tokens/jars lived in `/tmp` and were deleted. **I-5** — image digest read from the registry
header and pinned; pods run that exact digest. **I-6** — no port/topic/bucket changed. **I-8** —
ADR-025 written. **I-9** — scope: `deploy/phases/07-app-ingestion/**`, the git-mirror transport tag
(per-cycle exception, ADR-018), docs. **I-12** — touched trees build; dry-run admitted.

### Result — charter deviation closed

Gate 4 is now literally green: **API presign → URL on the public edge origin under /minio → browser
preflight → PUT the returned URL verbatim from the host → byte-identical object in MinIO → 202
commit → worker row in Postgres**. The Phase-8 charter exit criterion "browser presigned PUT works
from the frontend origin" is met without adaptation notes. Next unfinished phase: **Phase 9 —
Observability & hardening** (`deploy/phases/09-observability/`; alert→runbook gate per OPERATIONS
§10).
## Phase 9 — G9: observability gate through the real deployed surface (2026-10-03, k3d substrate)

### G9.0 — reconciliation of the working tree (the handoff premise was stale)

The handoff described an uncommitted Phase-9 build ("26 uncommitted changed files"). That was not
the state of the tree: `git status --porcelain` was empty and the Phase-9 work was already committed
in the stack `14275f3a … 181a378a`, with the mirror transport at `phase9-5` and all 16 Argo
Applications at that revision. Nothing was lost, restored or re-applied. The only git change this
pass made is the delivery fix in G9.5. Separately: Docker Desktop had been stopped, so the first
cluster read failed with connection-refused — the substrate was brought back up before any
conclusion was drawn, and the k3d cluster itself had survived intact.

```
$ git status --porcelain          # (empty)
$ git log --oneline -4
181a378a fix(phase-9): kube-state-metrics liveness answered on the main port, not telemetry
20870490 fix(phase-9): correct the two probe paths and pin config revisions
35514c19 chore(phase-9): advance the git transport to phase9-3
e1d3d357 fix(phase-9): three first-sync defects, each proven live
$ kubectl -n nagar-system get applications.argoproj.io \
    -o custom-columns=S:.status.sync.status,H:.status.health.status --no-headers | sort | uniq -c
     16 Synced   Healthy
$ kubectl -n nagar-system get deploy git-repo-mirror -o jsonpath='{…containers[0].image}'
k3d-nagar.localhost:5000/mission/git-repo-mirror:phase9-5
```

### G9.1 — the Grafana console, authenticated, with both provisioned datasources

```
$ kubectl -n nagar-observability port-forward --address 127.0.0.1 svc/nagar-grafana 3300:3300
Forwarding from 127.0.0.1:3300 -> 3300
$ curl -s --noproxy '*' http://127.0.0.1:3300/api/health
{ "database": "ok", "version": "11.4.0", "commit": "b58701869e1a11b696010a6f28bd96b68a2cf0d0" }
```

Opened in the browser through the preview tools; the persistent profile already held a live admin
session, so **no password was typed, read aloud or displayed** (and see G9.2: the seeded password is
not recoverable from the cluster at all). The dashboard
`/d/nagarvault-platform/nagarvault-e28094-platform-overview` rendered as "NagarVault — Platform
overview" with every panel live:

```
Scrape targets up              10
Pods not Running/Succeeded     No data
Alerts firing                  0   → 1  while the G9.5 drill ran
Certs expiring < 30d           0
Active series                  7792 → 8197
Edge requests by code          200 / 307 / 401 / 404   (exactly the G9.3 hits)
Edge 5xx by service            No data
Container restarts (15m)       populated; includes nagar-observability/p9-crashloop-drill during G9.5
Error-ish logs (Loki)          real lines — git-daemon "waitpid … No child process", Loki ingester
                               "entry too far behind", traefik "no servers found for nagar-app/ingestion"
                               during the restart, kafkajs ECONNREFUSED while Kafka came up, postgres
                               checkpoints
```

Connections → Data sources (`/connections/datasources`) — both provisioned sources exist:

```
Loki        Loki        http://nagar-loki.nagar-observability.svc.cluster.local:3100
Prometheus  Prometheus  http://nagar-prometheus.nagar-observability.svc.cluster.local:9090   [default]
```

### G9.2 — the Phase-8 app surface, reached through the deployed edge

```
$ kubectl -n nagar-system port-forward --address 127.0.0.1 svc/traefik-edge 8443:443
Forwarding from 127.0.0.1:8443 -> 443
$ curl -sk --resolve k3d-nagar.localhost:8443:127.0.0.1 -D - https://k3d-nagar.localhost:8443/
HTTP/1.1 307 Temporary Redirect
Location: /dashboard
<title>NagarVault — Officer Console</title>
$ curl -sk … https://k3d-nagar.localhost:8443/dashboard        → HTTP 200, 6467 bytes
$ curl -sk … -X POST -H 'Content-Type: application/json' \
    -d '{"files":[{"filename":"p9-telemetry.txt","contentType":"text/plain"}]}' \
    https://k3d-nagar.localhost:8443/api/v1/uploads/presign
{"detail":"missing session"}   HTTP 401
$ curl -sk … https://k3d-nagar.localhost:8443/api/v1/events/evt-p9
{"detail":"missing session"}   HTTP 401
$ kubectl -n nagar-app port-forward --address 127.0.0.1 svc/ingestion 13000:3000   # host TCP 3000 is taken
$ curl -s http://127.0.0.1:13000/       → {"status":"ok","service":"ingestion"}    HTTP 200
$ curl -s http://127.0.0.1:13000/health → {"api":true,"minio":true,"kafka":true}   HTTP 200
```

Two recorded notes. (a) **No authenticated `/api` call was made, deliberately:** the seeded admin
password is generated once by `seed_admin.py` and printed once (it is in no Secret — `kubectl -n
nagar-app get secrets` holds only `nagar-jwt`, `nagar-minio`, `nagar-postgres-app`, `edge-tls`), and
this pass was instructed not to re-seed. The API's documented boundary (401 `missing session` on both
`/api/v1` routes) plus the service's own 200 `/health` are the evidence instead. (b) The host already
had TCP 3000 bound by an **unrelated host process** (its `/health` answers a chat-bridge shape, not
ingestion's); the tunnel therefore used 13000 and that host service was left untouched.

### G9.3 — telemetry: one edge request produces a scrapeable metric *and* a log line

```
$ curl … 'http://127.0.0.1:9090/api/v1/query?query=sum(traefik_service_requests_total)'   # T0
3
   … exercised: GET /dashboard (200), POST /api/v1/uploads/presign (401), GET /api/v1/events/evt-p9 (401) …
$ curl … 'sum by (code,service,method) (traefik_service_requests_total)'                  # T+40s
401  POST  nagar-app-edge-ingestion-ba69e23eea182ac0ade7@kubernetescrd   1
401  GET   nagar-app-edge-ingestion-ba69e23eea182ac0ade7@kubernetescrd   1
200  GET   nagar-app-edge-frontend-ebcef7b90917ee187770@kubernetescrd    1
307  GET   nagar-app-edge-frontend-ebcef7b90917ee187770@kubernetescrd    1
404  GET   nagar-app-edge-ingestion-ba69e23eea182ac0ade7@kubernetescrd   1
404  GET   nagar-app-edge-auth-1e6aa3502fbd59742d9a@kubernetescrd         1

$ curl -G http://127.0.0.1:3100/loki/api/v1/query_range \
    --data-urlencode 'query={namespace="nagar-system",app="traefik-edge"} |= "presign"'
127.0.0.1 - - [03/Oct/2026:08:52:36 +0000] "POST /api/v1/uploads/presign HTTP/1.1" 401 28 "-" "-" 5
  "nagar-app-edge-ingestion-ba69e23eea182ac0ade7@kubernetescrd" "http://10.42.0.99:3000" 23ms
```

Path note, as the handoff allowed for: the mission profile's `/waiting` route does not exist — the 7e
app has no request logger and its only public routes are `/` and `/health`, neither of which the
edge's `/api` router can reach (`grep -rn waiting` over `deploy/phases/07-app-ingestion/ingestion/src/`
finds only the startup `console.log`). The documented substitute is the edge itself: Traefik runs with
`--accesslog=true` and serves its own metrics on the `ping` entrypoint, so **one** request yields both
the log line and the counter — and that counter is exactly what `Ingest5xxRate` is computed from
(ADR-026 §3).

### G9.4 — scrape targets, and the Loki deviation

```
$ curl -s http://127.0.0.1:9090/api/v1/targets   →  (health, job, instance)
up  alertmanager       10.42.0.79:9093
up  cert-manager       10.42.0.74:9402 · 10.42.0.88:9402 · 10.42.0.102:9402
up  cnpg-instances     10.42.0.106:9187 · 10.42.0.107:9187
up  kafka-exporter     10.42.0.98:9308
up  kube-state-metrics 10.42.0.97:8080        ← the source of kube_pod_container_status_waiting_reason
up  prometheus         localhost:9090
up  traefik            10.42.0.85:8082

$ curl … 'sum(up)'  → 10                       # agrees with the Grafana panel exactly
```

**Deviation, recorded rather than papered over:** there is no Prometheus target named `loki`. The
phase declares none on purpose — `prometheus.yaml`'s header says every job "targets a port that some
deployed object actually serves", and the job set is exactly prometheus / kube-state-metrics /
alertmanager / kafka-exporter / traefik / cert-manager / cnpg-instances (ADR-026 §1). Loki is
consumed as a **Grafana datasource** instead, and that was proven directly: `GET
http://127.0.0.1:3100/ready` → 200 and real log lines in the dashboard's Loki panel (G9.1, G9.3).
The handoff's "confirm a Target up … for loki" therefore has no target to confirm; adding one is a
scrape-list change, not part of this gate.

### G9.5 — the intentional alert drill: fixture → Alertmanager, carrying its runbook link

First run — this is where the real defect surfaced:

```
$ kubectl apply -f deploy/phases/09-observability/e2e/fixtures/crashloop-pod.yaml
pod/p9-crashloop-drill created                                                    # 08:54:10Z
t+20s   status=CrashLoopBackOff restarts=2  metric=0  alert=[]
t+80s   status=Error            restarts=4  metric=1  alert=[]        # kube-state-metrics saw it
t+100s  status=CrashLoopBackOff restarts=4  metric=1  alert=[pending p9-crashloop-drill]
t+160s  status=Error            restarts=5  metric=1  alert=[firing  p9-crashloop-drill]

$ curl … http://127.0.0.1:9090/api/v1/alerts
state   : firing
labels  : {"alertname": "PodCrashLooping", "container": "crasher", "namespace": "nagar-observability",
           "pod": "p9-crashloop-drill", "severity": "warning"}
annot   : {"runbook_url": "docs/OPERATIONS.md#rb-12.1",
           "summary": "Pod nagar-observability/p9-crashloop-drill container crasher is in CrashLoopBackOff"}
activeAt: 2026-10-03T08:55:37.110164408Z   value: 1e+00

$ curl … http://127.0.0.1:9090/api/v1/alertmanagers
active: []            ← nothing to deliver to
$ curl … http://127.0.0.1:9093/api/v2/alerts
total alerts in AM: 0
```

Root cause: `nagar-prometheus-config` carried a *scrape* job for Alertmanager's own metrics but no
`alerting:` block, so `firing` was terminal. The phase's own gate text ("applied until the alert
fires in Alertmanager with its `runbook_url` annotation"), the README's table and OPERATIONS §10 all
assume delivery, so the rule was only half of the I-7 contract. Fixed in commit `53a0f1fa` — an
`alerting.alertmanagers` static target on the Alertmanager service DNS, plus `nagar.io/config-rev:
1 → 2` so the pod actually rolls (the template is otherwise byte-identical; the earlier Alloy
incident on this substrate proved that trap).

Gates, then the sanctioned transport (§9.4 / §12.16):

```
$ kustomize build --load-restrictor LoadRestrictionsNone deploy/phases/09-observability   # 1919 lines
$ kustomize build deploy/phases/09-observability | kubectl apply --dry-run=server -f -    # admitted
$ promtool check config   (run inside the live pod; temp dir on the PVC, removed afterwards)
  SUCCESS: 1 rule files found
  SUCCESS: /prometheus/p9check/prometheus.yml is valid prometheus config file syntax
  SUCCESS: 5 rules found
$ docker build -t localhost:35000/mission/git-repo-mirror:phase9-6 deploy/phases/02-gitops/git-mirror
$ docker push  localhost:35000/mission/git-repo-mirror:phase9-6
  phase9-6: digest: sha256:213e564fad57a5cd573103f32a6a7540363580f6f9aa91d250ea25514bbb6146
$ kustomize build deploy/phases/02-gitops/git-mirror | kubectl apply --server-side --force-conflicts -f -
  deployment "git-repo-mirror" successfully rolled out
$ kubectl -n nagar-system exec deploy/git-repo-mirror -- sh -c 'git ls-remote git://127.0.0.1:9418/nagarvault.git HEAD'
53a0f1fa13217a6a0e0daa57c3f7d69b8dec6131
$ (Argo polls every ~3 min)
t+200s  argo=Synced/Progressing  rev=181a378a  prom-ready=/1   config-rev=2
t+240s  argo=Synced/Healthy      rev=53a0f1fa  prom-ready=1/1  config-rev=2
```

Delivery, re-read after the roll (the fixture was still crash-looping, so the rule re-fired):

```
$ curl … http://127.0.0.1:9090/api/v1/alertmanagers
active  : [{"url": "http://nagar-alertmanager.nagar-observability.svc.cluster.local:9093/api/v2/alerts"}]
dropped : []

$ curl … http://127.0.0.1:9093/api/v2/alerts        ← the proof this gate asked for
status.state   : active
startsAt       : 2026-10-03T09:17:07.110Z
updatedAt      : 2026-10-03T09:17:37.100Z
labels         : {"alertname": "PodCrashLooping", "cluster": "nagarvault", "container": "crasher",
                  "namespace": "nagar-observability", "pod": "p9-crashloop-drill", "severity": "warning"}
annotations    : {"runbook_url": "docs/OPERATIONS.md#rb-12.1",
                  "summary": "Pod nagar-observability/p9-crashloop-drill container crasher is in CrashLoopBackOff"}
receivers      : ['devnull']
generatorURL   : http://nagar-prometheus-568cb85675-sqnvf:9090/graph?g0.expr=max+by+(namespace,+pod,+container)+…

cross-check:  alertmanager alerts = 1 · prometheus firing = 1 · sum(up) = 10
in Grafana:   "Alerts firing" panel = 1 while the drill ran (screenshot + accessibility tree)
```

The runbook anchor is real (the other half of the drill), and the alert resolves on both sides when
the fixture goes away:

```
$ grep -n 'id="rb-12.1"' -A 1 docs/OPERATIONS.md
215:| <a id="rb-12.1"></a>12.1 | Pod `CrashLoopBackOff` | bad env/secret, dependency unreachable |
     `kubectl logs`; check §6.2 key map; verify NetworkPolicy allows the flow (SECURITY §8) |

$ kubectl delete -f deploy/phases/09-observability/e2e/fixtures/crashloop-pod.yaml
pod "p9-crashloop-drill" deleted from nagar-observability namespace
t+15s  prometheus=pending  alertmanager=0
t+60s  prometheus=none     alertmanager=0        ← resolved on both sides
```

### G9.6 — teardown, orphan check, and the invariants

```
$ kubectl -n nagar-observability get pod p9-crashloop-drill
Error from server (NotFound): pods "p9-crashloop-drill" not found
$ taskkill //F //IM kubectl.exe            → 0 remaining
$ netstat -ano | grep LISTENING | grep -E ':(13000|3300|8443|9090|9093|3100)\b'   → (empty)
$ kubectl -n nagar-system get applications.argoproj.io … | sort | uniq -c
     16 Synced   Healthy
$ kubectl get pods -A | grep -v -E "Running|Completed"        → (empty)
```

- **I-1** — the only git change this pass (`53a0f1fa`) reached the cluster through git → mirror →
  Argo. The out-of-band actions were the sanctioned §9.4 transport advance and the fixture
  apply/delete this gate prescribes; both are recorded above.
- **I-2** — the fix is idempotent (a static target, re-appliable forever); the drill is a no-op on re-run.
- **I-3** — no password, token or key was displayed anywhere. The Grafana proof rode the browser
  profile's existing session; the seeded admin password proved **unrecoverable** (generated once by
  `seed_admin.py`, never stored), so no login was attempted and none was needed.
- **I-5** — digest pins untouched; the mirror transport advances by `newTag` per ADR-018.
- **I-6** — no port, topic or bucket changed: the `alerting` target references the *existing*
  Alertmanager `:9093` service. The host-side tunnel on 13000 exists only because the host's own
  TCP 3000 was already occupied.
- **I-7** — the anchor is real and delivery is now proven, not assumed.
- **I-8** — no new ADR: the fix restores wiring the charter, README and OPERATIONS §10 already
  assumed, and ADR-026 never claimed a delivery mechanism, so no decision is being reversed.
- **I-9** — scope: `deploy/phases/09-observability/**`, the git-mirror transport tag (per-cycle
  exception, ADR-018), and the three docs whose contract changed (OPERATIONS §10, PHASES.md, the
  phase README).
- **I-12** — every touched tree builds; the server dry-run admits the phase.

### Result — fired, delivered, linked, resolved; and what Phase 9 still owes

The phase's "one alert intentionally fired and linked to its runbook" criterion is met **at the
Alertmanager**, not merely inside the rule engine: `PodCrashLooping` → `active` in Alertmanager with
`runbook_url: docs/OPERATIONS.md#rb-12.1`, after first exposing and then closing a real no-delivery
defect. Dashboards are populated (10/10 targets, 8197 active series, live Loki lines), the app
surface answers through the edge, and the restore-drill criterion was already satisfied by the
Phase-5 drill (G5.5, `RESTORE-DRILL-VERIFIED`).

**Still open for Phase 9 at this point:** the Kyverno admission gate —
`e2e/fixtures/policy-violation-pods.yaml` (tagged image, upstream registry and `hostNetwork` must
each be denied; the compliant control pod admitted). The full Kyverno set is deployed and Argo-clean;
only its adversarial verification was outstanding, so PHASES.md recorded the entry as IN PROGRESS.
**That gate was run next (G9.8, same day) and passed, so the ledger is now Done** — see the two
sections below. The exact next unfinished phase is therefore Phase 10 — parity cutover & cleanup.
### G9.7 — closure checkpoint: transport advanced so Argo's revision equals HEAD

G9.1–G9.6 above were recorded in the docs commit `163b6769`, which the mirror did not yet carry (the
`phase9-6` payload was cloned before it — the ADR-018 circularity §12.16 names: Argo cannot learn a
new revision until the operator rebuilds the transport, and the rebuild commit is itself the thing
being published). This commit performs the one-per-cycle advance to `phase9-7` so the mirror serves
HEAD, giving a steady state where Argo's `targetRevision: HEAD` resolves to the recorded state:

```
$ git clone --bare . deploy/phases/02-gitops/git-mirror/payload/nagarvault.git
$ docker build -t localhost:35000/mission/git-repo-mirror:phase9-7 deploy/phases/02-gitops/git-mirror
$ docker push  localhost:35000/mission/git-repo-mirror:phase9-7
$ kustomize build deploy/phases/02-gitops/git-mirror | kubectl apply --server-side --force-conflicts -f -
$ kubectl -n nagar-system exec deploy/git-repo-mirror -- git ls-remote git://127.0.0.1:9418/nagarvault.git HEAD
   → this commit
```

The phase's manifests were unchanged by `163b6769` (docs only), which is why every Application read
`Synced/Healthy` at `53a0f1fa` throughout — the advance is transport hygiene, not a state change.
### G9.8 — the Kyverno admission gate (the fixture's own "G9.6" probe)

The last verification PHASES.md named as outstanding. Pre-state, so the result is attributable:

```
$ kubectl get clusterpolicies --no-headers
disallow-host-access           true   true   True   38h     Ready   ← phase 9
disallow-latest-tag            true   true   True   2d14h   Ready   ← baseline
require-image-digest           true   true   True   38h     Ready   ← phase 9
require-nagar-labels           true   true   True   2d14h   Ready   ← baseline
require-pod-security-context   true   true   True   2d14h   Ready   ← baseline
restrict-image-registries      true   true   True   38h     Ready   ← phase 9
$ kubectl -n kyverno get pods --no-headers   → 4/4 Running (admission, background, cleanup, reports)
$ kubectl -n nagar-system get applications…  → 16 Synced Healthy
```

**The probe.** Applied the fixture exactly as the README prescribes (`APPLY-EXIT=1` is the
expected outcome — three of four objects must be rejected):

```
$ kubectl apply -f deploy/phases/09-observability/e2e/fixtures/policy-violation-pods.yaml
APPLY-EXIT=1
pod/p9-control-compliant created
Error from server: error when creating "…/policy-violation-pods.yaml": admission webhook
"validate.kyverno.svc-fail" denied the request:

resource Pod/nagar-observability/p9-violation-tag-only was blocked due to the following policies

require-image-digest:
  digest-pinned-app-and-observability: 'validation error: Every container image must
    be pinned by digest (@sha256:…) — I-5. rule digest-pinned-app-and-observability
    failed at path /spec/containers/0/image/'

Error from server: error when creating "…/policy-violation-pods.yaml": admission webhook
"validate.kyverno.svc-fail" denied the request:

resource Pod/nagar-observability/p9-violation-registry was blocked due to the following policies

restrict-image-registries:
  internal-registry-app-and-observability: 'validation error: Images must come from
    the internal registry — k3d-nagar.localhost:5000 (registry.nagar.internal:5000)
    only (I-11). rule internal-registry-app-and-observability[0] failed at path /spec/containers/0/image/
    rule internal-registry-app-and-observability[1] failed at path /spec/containers/0/image/'

Error from server (Forbidden): error when creating "…/policy-violation-pods.yaml":
pods "p9-violation-hostnet" is forbidden: violates PodSecurity "restricted:v1.31":
host namespaces (hostNetwork=true)
```

Exactly three denied and one admitted, as the README and PHASES.md require — but the third
message is **not** Kyverno's webhook, and the fixture's own header comment implied it was. The
control ran to completion rather than merely being accepted:

```
$ kubectl -n nagar-observability get pod --no-headers | grep '^p9-'
p9-control-compliant   0/1   Completed   0   55s
$ kubectl -n nagar-observability logs p9-control-compliant
p9 control: admitted
$ for p in p9-violation-tag-only p9-violation-registry p9-violation-hostnet; do …
p9-violation-tag-only    absent (denied)
p9-violation-registry    absent (denied)
p9-violation-hostnet     absent (denied)
```

**The precedence finding (why one policy needed a second probe).** Every mission namespace runs
PSA `restricted`, and the in-tree PodSecurity admission plugin is evaluated *before* external
validating webhooks, so inside those namespaces it answers `hostNetwork` first and
`disallow-host-access` is never reached:

```
$ kubectl get ns -L pod-security.kubernetes.io/enforce
nagar-app / nagar-observability / nagar-platform / nagar-system / kyverno / cert-manager
                              enforce=restricted
default / kube-system / kube-public / kube-node-lease   (no pod-security labels → privileged)
```

`disallow-host-access` is still Enforce and matches every namespace except `kube-system*`, so it
was probed where PSA does not preempt it — `default`, using `--dry-run=server` so admission runs
in full and nothing is persisted, with a negative control isolating `hostNetwork` as the sole
variable:

```
$ kubectl apply --dry-run=server -f agentic/tmp/p9-hostnet-probe.yaml      # namespace: default
EXIT=1
Error from server: error when creating "…": admission webhook "validate.kyverno.svc-fail"
denied the request:

resource Pod/default/p9-probe-hostnet-kyverno was blocked due to the following policies

disallow-host-access:
  no-host-namespaces: 'validation error: hostPath volumes, hostNetwork, hostPID and
    hostIPC are forbidden (SECURITY §5 hardening; the PSS restricted profile already
    forbids the volume type, this names the whole family). rule no-host-namespaces
    failed at path /spec/hostNetwork/'

$ kubectl apply --dry-run=server -f agentic/tmp/p9-hostnet-control.yaml    # identical, no hostNetwork
EXIT=0
pod/p9-probe-control-kyverno created (server dry run)
$ kubectl -n default get pod --no-headers | grep p9
(no p9 pods in default)
```

All three Phase-9 policies have now each decided a real admission request, and the compliant
control proves none of them over-blocks.

**The violation reporting path (SECURITY §8).** §8 promises violations are "admission-denied and
reported via Kyverno's own reports-controller (`kubectl get policyreport -A`, plus the
controller's `/metrics`)" — both halves verified:

```
$ kubectl get policyreport -A -o json  → 154 reports, 1061 results
status counts : {'pass': 1027, 'fail': 34}
FAIL by policy: {'require-nagar-labels': 10, 'require-pod-security-context': 24}
FAIL by ns    : {'kyverno': 32, 'nagar-system': 2}
$ kubectl -n kyverno port-forward svc/kyverno-reports-controller-metrics 8000:8000
$ curl -s http://127.0.0.1:8000/metrics
HTTP 200 bytes=471788          (1209 lines beginning kyverno_)
kyverno_policy_execution_duration_seconds_bucket{policy_name="disallow-host-access",
  policy_validation_mode="enforce",rule_execution_cause="background_scan",
  rule_result="pass",resource_kind="Deployment",…} 129
```

The **Phase-1 baseline** policies scope to every namespace except `kube-system*`, so they flag the
control planes too. 32 of the 34 failures are in `kyverno` (a bundle namespace); the other **2 are
in `nagar-system`, a mission namespace** — `Pod/sealed-secrets-controller` failing
`require-nagar-labels` (CONVENTIONS §5). They are pre-existing and Phase-1's to fix, and they are
recorded here because they make the reporting path demonstrably live rather than vacuously green —
but the earlier gloss that they are all "Kyverno's own workloads" with "zero fails in any mission
namespace" was **wrong** (gap 2), and it survived only because the check meant to prove it could
not fail. The three Phase-9 policies report zero failures against the running
estate, which is the scoping claim `policies.yaml`'s header makes.

There is deliberately **no Prometheus alert** on policy violations: Kyverno is not one of the
seven scrape jobs ADR-026 §1 enumerates, and ADR-026 §3 defers the `policy-reporter` UI. PolicyReports
plus the controller's `/metrics` are the documented surface, so no alert existed to fire.

**Teardown and invariants.**

```
$ kubectl delete -f …/e2e/fixtures/policy-violation-pods.yaml
Error from server (NotFound): … pods "p9-violation-tag-only" not found
Error from server (NotFound): … pods "p9-violation-registry" not found
Error from server (NotFound): … pods "p9-violation-hostnet" not found
   (only the control existed and was deleted; the three NotFound lines are the denied probes,
    which never were created — so a re-run of the delete is a no-op → idempotent, I-2)
$ kubectl -n nagar-observability get pod | grep '^p9-'   → (no p9 pods)
$ kubectl -n default           get pod | grep '^p9-'    → (no p9 pods)
$ tasklist //FI "IMAGENAME eq kubectl.exe"              → No tasks are running
$ netstat | grep LISTENING | grep -E ':(8000|13000|3300|9090|9093|3100|8443)\b'  → (empty)
```

- **I-1** — no live mutation beyond the admission probes themselves: the control pod is the only
  object the gate persisted, and it was deleted; the two Kyverno probes used `--dry-run=server`
  and persisted nothing. The changes this pass ships (fixture header + PHASES.md + this log) reach
  the cluster only through git → mirror → Argo.
- **I-2** — apply is re-runnable: denials are deterministic and the delete tolerates what never existed.
- **I-3** — no secret, token or password was read or displayed.
- **I-5 / I-11 / I-12** — the gate is the *enforcement proof* for I-5 (digest) and I-11 (registry
  allowlist); `e2e/fixtures/` is not listed in the phase `kustomization.yaml`, so the header edit
  changes no applied resource and both trees still build.
- **I-9** — scope: `deploy/phases/09-observability/e2e/fixtures/**`, `docs/PHASES.md`, this log.

### G9.8b — the PolicyViolation event path: the deny is recorded, not just returned

SECURITY §8 promises violations are "admission-denied **and reported**". Each of the three denials
above left three independent traces — the webhook response, a `Warning/PolicyViolation` Event, and
Kyverno's own admission log:

```
$ kubectl get events -A --no-headers | grep -i p9-violation
default 17m Warning PolicyViolation clusterpolicy/require-image-digest
  Pod nagar-observability/p9-violation-tag-only: [digest-pinned-app-and-observability] fail (blocked);
  … Every container image must be pinned by digest (@sha256:…) — I-5.
  rule digest-pinned-app-and-observability failed at path /spec/containers/0/image/
default 17m Warning PolicyViolation clusterpolicy/restrict-image-registries
  Pod nagar-observability/p9-violation-registry: [internal-registry-app-and-observability] fail (blocked);
  … Images must come from the internal registry — k3d-nagar.localhost:5000 (registry.nagar.internal:5000)
  only (I-11). rule internal-registry-app-and-observability[0] failed at path /spec/containers/0/image/
  rule internal-registry-app-and-observability[1] failed at path /spec/containers/0/image/
default 13m Warning PolicyViolation clusterpolicy/disallow-host-access
  Pod default/p9-probe-hostnet-kyverno: [no-host-namespaces] fail (blocked); … hostPath volumes,
  hostNetwork, hostPID and hostIPC are forbidden (SECURITY §5 …) … failed at path /spec/hostNetwork/

$ kubectl get events -A --no-headers | grep -o 'clusterpolicy/[a-z0-9-]*' | sort | uniq -c
      1 clusterpolicy/disallow-host-access
      1 clusterpolicy/require-image-digest
     10 clusterpolicy/require-nagar-labels
     24 clusterpolicy/require-pod-security-context
      1 clusterpolicy/restrict-image-registries

$ kubectl -n kyverno logs deploy/kyverno-admission-controller --since=60m \
    | grep -E 'validation failed|admission request denied' | grep p9-
09:55:08Z TRC validation.go:125 > validation failed action=Enforce
    failed rules=["digest-pinned-app-and-observability"] name=p9-violation-tag-only
    namespace=nagar-observability operation=CREATE policy=require-image-digest
09:55:08Z INF handlers.go:165 > admission request denied name=p9-violation-tag-only
    namespace=nagar-observability operation=CREATE
09:55:08Z TRC validation.go:125 > validation failed action=Enforce
    failed rules=["internal-registry-app-and-observability"] name=p9-violation-registry
    namespace=nagar-observability operation=CREATE policy=restrict-image-registries
09:55:08Z INF handlers.go:165 > admission request denied name=p9-violation-registry
    namespace=nagar-observability operation=CREATE
09:58:09Z TRC validation.go:125 > validation failed action=Enforce
    failed rules=["no-host-namespaces"] name=p9-probe-hostnet-kyverno
    namespace=default operation=CREATE policy=disallow-host-access
09:58:09Z INF handlers.go:165 > admission request denied name=p9-probe-hostnet-kyverno
    namespace=default operation=CREATE
```

Two notes for whoever runs this next. (1) The per-policy event counts sum `10 + 24 = 34` for the
baseline findings, exactly the PolicyReport FAIL total above — Events and reports are two views of
the same findings, so they corroborate rather than merely coexist. (2) `kubectl get events
--field-selector source=kyverno` returns "No resources found": Kyverno writes these Events without
that field, so filtering on it silently hides every violation — grep the message instead.

Kyverno's admission controller also confirms `action=Enforce` for each, i.e. these were real
Enforce decisions, not Audit warnings. Together with the webhook response, PolicyReports and the
controller's `/metrics`, all four surfaces of the documented reporting path are proven; there is
still no Prometheus alert on violations by design (not a scrape job, ADR-026 §1).

### Result — Phase 9 gate green; ledger flipped to Done

All four README gate fixtures have now been exercised: the `PodCrashLooping` drill fired **and
reached Alertmanager** with its runbook (G9.5), and the Kyverno admission probes denied three of
four with the compliant control admitted (G9.8). Combined with G9.1–G9.4 (console, app surface,
telemetry, targets) and G5.5's restore drill, PHASES.md's Phase-9 exit criteria — dashboards
populated; one alert intentionally fired and linked to its runbook; restore drill evidence
recorded — are all met, so the entry is now **Done 2026-10-03**.

**Exact next phase: Phase 10 — Parity cutover & cleanup**, whose entry gate is OPERATIONS §11's
smoke script green on Kubernetes plus the parity checklist, and whose first actions are verifying
the Compose remnants are absent (ADR-013), auditing stray tracked `.env` files, resolving the
nested `frontend/frontend/Dockerfile`, rewriting the README, and flipping this ledger to
"Complete."
---

## Phase 10 — Parity cutover & cleanup (2026-10-03, k3d substrate)

### G10.0 — Charter reconciliation: what Phase 10 says vs what the tree holds

Read before touching anything: PHASES.md §2 Phase-10 block, OPERATIONS §11 (+ its invocation
note), ADR-004, ADR-013, ADR-024, CONVENTIONS §4, AGENTS.md. Five disagreements between the
charter's words and the repository, recorded first (mission rule 6) so nothing is coded around a
stale sentence:

| # | Document says | Tree actually holds | Decision |
|---|---|---|---|
| 1 | "delete `docker-compose.yml`, `docker-compose.dev.yml`, all per-service `Dockerfile`s and `.dockerignore`s (ADR-004)" | 0 tracked compose files, 0 `.dockerignore`s; 12 tracked `Dockerfile`s, every one under `deploy/phases/**` | ADR-013 §1 and §3 already superseded ADR-004 for this substrate: Phase 10 **verifies** absence and **keeps** the new per-service build recipes. This subphase is therefore verification, not deletion — raw output in G10.4. |
| 2 | "audit stray tracked `.env` files (several per-service `.env` files exist today)" | `git ls-files \| grep '(^\|/)\.env'` → none; `find` → no `.env` anywhere in the tree | Day-0 statement predating the rebuild. The audit still runs and is recorded **already clean** (G10.4). |
| 3 | "resolve the nested `frontend/frontend/Dockerfile` duplicate" | no such path tracked or on disk; exactly one `deploy/phases/07-app-ui/frontend/Dockerfile` | Already resolved by the rebuild (ADR-013 §2). Recorded as **not present**; nothing to do. |
| 4 | README: "Until Phase 10 completes, the frozen `docker-compose*.yml` files remain the only runnable path" | no compose file exists in the tree; Phases 0–9 are Done | False today → README rewrite, the charter's own action (G10.6). |
| 5 | OPERATIONS §11 step 5: "ask: `POST /ask` via edge (expect sql + data)" | ADR-024 §5 froze the edge map (`/`→frontend:3001, `/api`→ingestion:3000) and explicitly does **not** route slmService; the console's own BFF paths are shadowed by the `/api` router | Real defect, live-proven in G10.1 — the officer console cannot log in through the public edge. Fixed through the sanctioned path (ADR-027, G10.2). |

One more staleness outside the charter block: **AGENTS.md §7 still says "Phases 9–10 are not yet
implemented"** although Phase 9 closed at `e580f46e`. Refreshed with the ledger flip under the
same precedent as G8.7 ("AGENTS.md §7 refreshed").
### G10.1 — Entry gate: OPERATIONS §11 smoke script green on Kubernetes

**This subphase is proven on the live cluster — the script ran, SMOKE-RESULT: 6/6 PASS, exit
code 0.** The `deploy/phases/10-parity-cutover/e2e/e2e-smoke.py` driver (stdlib-only Python,
the house driver style of `07-app-admin/e2e/e2e-cluster.py`, 313 lines, committed at HEAD
`37e23c2a`) owns the whole §11 invocation note that G8.7 documented for curl — spawn the
`traefik-edge` port-forward, poll until the edge answers, run all six steps over TLS through that ONE
tunnel, kill it on exit — because a cross-command forward dies with its parent shell. Three host-side
substitutions are forced and recorded in the script's own docstring: an unverified TLS context for
curl's `-k` (the internal CA is not in the host trust store), no revocation option at all (Python does
not do schannel), and a literal `Host:` header for `--resolve`. One subtlety worth keeping: the edge's
`TLSOption` sets `sniStrict: true` and Python sends no SNI for a literal IP (RFC 6066 §3), so the
driver keeps the real hostname for SNI and Host and redirects only the DNS lookup — the exact thing
`--resolve` does.

The seed was created through the sanctioned §5 ritual — `kubectl exec` the auth pod's
`seed_admin.py --username p10gate5 --user-id p10gate5-001`; the password is generated and printed
**once** to stdout, captured to a shell variable in the same invocation, and **never echoed** (I-3).
`seed_admin.py` emits the password on its second line (`ADMIN PASSWORD (record in the operator
vault; shown once):
<password>
`), so the harness reads line 2 — a real trap, because a naive
`sed 's/.*: //'` matches the label line, not the password. The officer for step 5 is minted in-band
through the admin-gated `POST /auth/create` (the precedent of G7g.3/G8R.5); its password is generated
in-process with `secrets.token_urlsafe(18)` and never printed. Admin is deliberately **not** used for
the ask: an admin ask is denied by table-rbac (SECURITY §3), so an admin-only run would have failed for
the wrong reason.

The DB the script queries is `nagardb` (not `nagar`), reachable from inside the Postgres pod via TCP
to `postgres-rw.nagar-platform.svc.cluster.local` using the bootstrap secret's `username`/`password`
keys (not `adminPassword`) with `PGPASSWORD` set — the pod is `postgres-1` (the CNPG-managed name),
not `nagar-app-postgres-13-2`; a Unix-socket `psql -U nagar -d nagar` inside that pod hits peer auth
and the name `nagar-app-postgres-13-2` does not exist as a Deployment, so the script's `db_scalar()`
is the correct path and the earlier ad-hoc attempts that failed were quoting/name errors, not cluster
defects.

**Live run — 6/6 PASS, exit code 0:**

    --- OPERATIONS §11 smoke, edge https://k3d.nagar.internal:4431 (tunnel spawned here) ---
    SMOKE-1-OK  GET /auth/  HTTP 200 {"status":"ok","service":"authService"}
    SMOKE-2-OK  POST /auth/login (seeded admin)  HTTP 200 Set-Cookie: session_token=<redacted>;
                HttpOnly; Max-Age=3600; Path=/; SameSite=lax; Secure
            nmc_complaints before ingest: 6
    SMOKE-3-OK  POST /api/v1/events (JSON only)  HTTP 202 nmc.complaints.raw.restricted.v1
                evt-78a3d58e-d494-41ee-81ea-300cd160acf9
    SMOKE-4-OK  enrich lands in PostgreSQL nmc_complaints  6 -> 7
            POST /auth/create (admin-gated) -> HTTP 200 {"status":"ok",}
                "user_id":"p10smoke-1791033774-9909917b","username":"p10smoke-1791033774",
                ...}
    SMOKE-5-OK  POST /api/ask (officer, via edge + BFF)  HTTP 200
                sql='SELECT COUNT(event_id) FROM nmc_complaints' rows=1 role=nmc_officer
    SMOKE-6-OK  GET /admin/health/cluster  HTTP 200
                {"db":true,"kafka":true,"schemaIndexer":true,"all":true}
    SMOKE-RESULT: 6/6 PASS
    tunnel torn down

Every marker is present and correct. Step 2 carries `Secure` — the earlier harness bug (reading
`dict(resp.headers)` for the cookie attributes instead of the original `Set-Cookie` list, which
keys on the wire case `Set-Cookie` and keeps only the first value so `.get("set-cookie")` silently
returns `None`) is fixed in `cookie_attrs()` and **documented there** so it cannot be reintroduced;
the trap was found live in a prior turn and is now guarded. Step 3 returns a real `eventId` (UUID form,
`evt-...`) and a server-chosen topic (`nmc.complaints.raw.restricted.v1`), and step 4 confirms the
enrich landed (6 → 7). Step 5 returns a real SQL and rows through the BFF route `/api/ask` over the
edge — which is exactly the end state §11 asks for, even though §11 writes "POST /ask via edge":
slmService is deliberately **not** edge-routed (ADR-024 §5), the console's own ask surface is the BFF
route `/api/ask` (ADR-023), and ADR-027 put that BFF route back behind the edge in the previous
subphase, so `/api/ask` via the public edge is the same officer-ask outcome §11 prescribes. Step 6
reports all four health gates true (`db`, `kafka`, `schemaIndexer`, `all`).

The script's own exit contract holds: `return 0 if _failed == 0 and total == 6 else 1`, and that
returned 0. Re-runs are idempotent (I-2): the seed produces a new timestamped admin identity
(`p10gate5-001`), the in-band officer mint produces a new `p10smoke-<ts>` identity, and the step-3
ingest produces a new `evt-...` row from `source_system='ops-smoke'` — none collide with prior runs.

**Charter-vs-script note (recorded, not hidden).** §11 step 5 says "ask: `POST /ask` via edge";
the script exercises `POST /api/ask` through the edge+BFF instead. This is the one intentional
departure from the literal §11 wording and it is recorded in the script itself (lines 275–281:
"§11 writes 'POST /ask via edge'; slmService is deliberately not edge-routed (ADR-024 §5) and the
console's own surface is the BFF route /api/ask (ADR-023), which ADR-027 put back behind the edge")
and above. The departure is justified by the frozen edge map and the BFF architecture, and the
end state — a real ask answered with SQL and rows, through the public edge, by an officer session —
is what §11 is actually testing.

**Invariants.** **I-1** — this subphase changed **nothing** in the cluster manifests, images, or
config; the only cluster-side effects were the sanctioned §5 seed (one new admin identity), the
in-band officer creation, and the step-3 ingest — all read-only-on-manifests, all idempotent.
**I-2** — the seed, the officer mint and the ingest are all idempotent; re-runs create new
timestamped identities and a new event id rather than colliding. **I-3** — no password, token or
cookie value was displayed anywhere: the seed printed once into a shell variable, the driver redacts
the cookie to `session_token=<redacted>`, and the officer password lives only in a Python variable
and is never logged. **I-6** — no port, topic or bucket changed. **I-9** — the smoke run itself
touches only the mission log as a document; the script lives in the Phase-10 subtree
(`deploy/phases/10-parity-cutover/e2e/e2e-smoke.py`) and is committed at HEAD `37e23c2a`
(phase10-3 transport). **I-12** — the touched tree (`deploy/phases/10-parity-cutover`) builds under
`kustomize build --load-restrictor LoadRestrictionsNone` and the dry-run admits (gates run in G10.2
recording).

**Result — the Phase-10 entry gate is green.** OPERATIONS §11 steps 1–6 pass end to end against the
live cluster over TLS through the real edge, scripted and repeatable (`python
deploy/phases/10-parity-cutover/e2e/e2e-smoke.py`), and the run found no live defect this time — the
two earlier failures (step-2 cookie-attribute parse, step-5 Qdrant search path) were both already
fixed upstream (ADR-028 for the indexer/search path, the `cookie_attrs()` fix for step 2) and this
run is the verification that they hold against the live cluster. Next subphase: **G10.2 — the parity
checklist**, then Compose/.env/Dockerfile verification (G10.3–G10.5), the README rewrite (G10.6), and
the ledger flip (G10.7).

**Closure note (2026-10-03) — the gate is now WITNESSED, not inherited.** The `6/6 PASS` recorded
above was, until this pass, inherited from the earlier live run. Re-running it at closure found a
real defect first, and the gate is green again on three consecutive witnessed executions.

***1. The failure.*** The first fresh run returned **5/6, exit code 1**:
`SMOKE-5-FAIL POST /api/ask (officer, via edge + BFF)  HTTP 403 {"detail":{"reason":"table-rbac",
"verdict":"blocked"}}`. The audit row (`audit_logs`, source `queryService`, actor
`p10smoke-1791043371-be3667a3`, role `nmc_officer`) shows what the model actually generated for
"How many complaints are in the warehouse?":

    SELECT COUNT(*) FROM health_camp_records WHERE media_bucket IS NOT NULL

`nmc_officer` is deliberately not permitted on `health_camp_records` (`ROLE_TABLES`, SECURITY §3), so
**that 403 was the gate working correctly** — it caught a mis-targeted query, not a wiring fault. The
identical input had produced `SELECT COUNT(event_id) FROM nmc_complaints` (allowed) on the earlier
run, and two further runs of the *unchanged* vague question also passed, so the model's table choice
is per-sample non-deterministic (1 fail in 4 observed) even at `temperature: 0` — it is the retrieved
context, not the sampler, that varies.

***2. The in-scope fix*** (`deploy/phases/10-parity-cutover/e2e/e2e-smoke.py`, Phase-10 subtree).
§11 step 5 tests the ask **path** (edge → BFF → slmService → queryService → SQL + rows), not the
model's accuracy, so the probe must not hinge on the model's per-sample table choice. The question
now names the table it means ("How many rows are in the nmc_complaints table?"), removing that
choice at the source. The assertion is unchanged — a real `200` carrying SQL and rows is still
required, so a cluster where the officer can never get a valid answer still fails.
An earlier attempt at the same fix (`e368d467`) also re-asked a `403` up to three times; that block
was **removed** once the reword alone was shown to answer on the first attempt in every run (the
2026-10-03 audit flagged it as unexercised dead machinery, and deleting it re-proved the gate).

***3. The witnessed run.*** Method exactly as §5/§11 prescribe: seed a fresh admin through the
sanctioned out-of-band ritual (`kubectl -n nagar-app exec deploy/auth-service -- python
seed_admin.py --username … --user-id …`), read the one-time password from **line 2** of that output
into a shell variable and never display it (I-3), then `NV_ADMIN_USER=… NV_ADMIN_PASSWORD=… python
deploy/phases/10-parity-cutover/e2e/e2e-smoke.py` — the driver spawns its own edge tunnel and mints
its officer in-band through the admin-gated `POST /auth/create`. Three consecutive runs
(2026-10-03T16:06:33Z, 16:06:47Z, 16:06:53Z) each printed all six markers, `SMOKE-RESULT: 6/6 PASS`
and **exit code 0**:

    --- OPERATIONS §11 smoke, edge https://k3d.nagar.internal:4431 (tunnel spawned here) ---
    SMOKE-1-OK  GET /auth/  HTTP 200 {"status":"ok","service":"authService"}
    SMOKE-2-OK  POST /auth/login (seeded admin)  HTTP 200 Set-Cookie: session_token=<redacted>;
                HttpOnly; Max-Age=3600; Path=/; SameSite=lax; Secure
    SMOKE-3-OK  POST /api/v1/events (JSON only)  HTTP 202 nmc.complaints.raw.restricted.v1
                evt-0237fd8c-00db-4088-897a-51d7624967f0
    SMOKE-4-OK  enrich lands in PostgreSQL nmc_complaints  10 -> 11
            POST /auth/create (admin-gated) -> HTTP 200 {"status":"ok","user_id":"p10smoke-…",…}
    SMOKE-5-OK  POST /api/ask (officer, via edge + BFF)  HTTP 200
                sql='SELECT COUNT(*) FROM nmc_complaints' rows=1 role=nmc_officer
    SMOKE-6-OK  GET /admin/health/cluster  HTTP 200
                {"db":true,"kafka":true,"schemaIndexer":true,"all":true}
    SMOKE-RESULT: 6/6 PASS
    EXIT CODE: 0

Step 4 saw `11 -> 12` and `12 -> 13` on runs 2 and 3; step 5 answered on the **first** attempt in all
three runs, which is the evidence that the reworded question alone removed the mis-targeting. Item
2's archived `nmc_complaints|7` baseline still holds as history; the live count at closure is **13**
because this gate's own step-3 ingests add a fresh row per run (new `sourceRecordId` each time, so
the upsert never collides — the I-2 witness).

***4. Open finding, recorded not fixed (out of Phase-10 scope).*** The model behaviour underneath the
failure is real and an operator will meet it: for a vague "complaints" question, Qwen3 1.7B sometimes
emits a `health_camp_records` query and earns a correct 403. That is an slmService retrieval/prompt
quality issue in the `07-app-slm` subtree, which I-9 keeps this phase out of, and it belongs in the
handover report's known-gaps list — not hidden behind the gate's retry.

### G10.2 — Parity checklist: nine items, each proven live

The checklist is the phase's substance, so every line below is measured, not cited. Items 1 and 2
needed new evidence: **no gate in this mission had ever produced a `water`, `health` or `ev`
event** — `complaints` (and `traffic`) had carried all of them — so the checklist was exercised for
real rather than inferred from a working path.

**1. All 6 topics consumed.** The worker subscribes to the **five** raw topics; the sixth,
`nmc.complaints.dlq.v1`, is *produced* by the worker and *consumed* by adminService (7f) — so
"consumed" is satisfied across the two roles, and both halves are proven below.

    enrichWorker    ev.bus.telemetry.raw.v1          0     2     2     0   rdkafka-91c8fd1d…
    enrichWorker    health.camps.raw.v1              0     2     2     0   rdkafka-91c8fd1d…
    enrichWorker    nmc.complaints.raw.restricted.v1 0     7     7     0   rdkafka-91c8fd1d…
    enrichWorker    traffic.events.raw.v1            0     2     2     0   rdkafka-91c8fd1d…
    enrichWorker    water.sensors.raw.v1             0     2     2     0   rdkafka-91c8fd1d…

**LAG 0 on all five** — the log-end offset equals the committed offset, so nothing is pending.

**2. All 5 dept tables written.** Five real events, one per department, through the edge
(`POST /api/v1/events`, `HTTP 202` each, server-chosen topic returned), then the worker:

      complaints  HTTP 202  topic=nmc.complaints.raw.restricted.v1  evt-be549991-045f-4ba8-a32c-faeaf86dddb6
      traffic     HTTP 202  topic=traffic.events.raw.v1             evt-af644815-c418-41ca-a8ec-c5db976db9e2
      water       HTTP 202  topic=water.sensors.raw.v1              evt-0bf2bbde-bd8d-4354-a242-f9b93eec869f
      health      HTTP 202  topic=health.camps.raw.v1               evt-f05ef453-af35-44b7-a068-07c2b86a2b30
      ev          HTTP 202  topic=ev.bus.telemetry.raw.v1           evt-257f358d-bf27-477e-8dc0-6f41908fddf3

    nmc_complaints|7   traffic_events|2   water_sensor_readings|2   health_camp_records|2   ev_bus_telemetry|2
    rows written by THIS run (source_system='p10-parity'):
      complaints|2  traffic|2  water|2  health|2  ev|2

Two rows per table is the run being repeated after the fix below — i.e. the upsert is genuinely
idempotent on `(source_system, source_record_id)`, which is the I-2 witness as well.

**This item found a real defect, and it was a serious one.** The first attempt wrote `complaints`
and `traffic` and then stopped: the worker had **crashed** and entered `CrashLoopBackOff` (9
restarts), so every department after the first bad one stayed unenriched:

    psycopg.errors.UndefinedColumn: column "media_bucket" of relation
    "water_sensor_readings" does not exist
      File "/app/enrich.py", line 240, in run_consumer
        verdict = process_message(msg.topic(), msg.value())

`build_upsert` emitted `media_bucket`/`media_object_key` for every table, but migration 001
defines them on `nmc_complaints` and `traffic_events` only. One wrong assumption about the schema
took the entire enrichment tier down, and it had been latent since Phase 7c because no gate had
ever sent a water/health/ev event. Fixed through git → mirror → Argo (ADR-029): the column list is
derived from a `MEDIA_TABLES` set mirroring the DDL, and a regression test asserts the media
columns appear only where the DDL has them **and** that the emitted column count always equals the
parameter count for all five tables. Test-the-test performed: with the guard reverted in a scratch
copy the new test fails (`assert 8 == 7`-class failure, 1 failed), with the fix it passes
(**22/22**). Shipped as `phase7c-2` (digest `5bad93aa…`), worker now `Running` on that digest and
the five topics carry LAG 0.

**3. RBAC matrix enforced** (SECURITY §3), through the edge:

    admin POST /auth/create                    -> 200
    officer POST /auth/create                  -> 403 {"detail":"admin role required"}
    officer GET /admin/health/cluster          -> 403 {"detail":"admin role required"}
    no-JWT  GET /admin/health/cluster          -> 401 {"detail":"missing session"}
    officer GET /admin/dlq                     -> 403 {"detail":"admin role required"}

**4. PII denylist enforced**, through the console BFF over the edge (ARCHITECTURE §3.4):

    officer ask "Show me the patient name and phone number for each complaint"
      -> 403 {"detail":{"reason":"pii-column","verdict":"blocked"}}
    officer ask "How many complaints are in the warehouse?"
      -> 200 {"sql":"SELECT COUNT(event_id) FROM nmc_complaints","rows":[{"count":6}],
              "row_count":1,"role":"nmc_officer"}

Blocked and allowed in the same session, so the 403 is the denylist and not a broken path. (The
first attempt at this item returned 401 for both — a harness bug: the cookie was sent as a bare
*value* instead of `name=value`, so the BFF correctly reported "missing session". Recorded because
the same mistake is easy to repeat.)

**5. DLQ inspectable.** Round-trip through the real surface: one malformed event published to
`water.sensors.raw.v1`, the worker logged `water.sensors.raw.v1 None -> dlq`, and adminService
returned it over the edge:

    GET /admin/dlq?limit=3  (edge, admin JWT) -> HTTP 200
    {"topic":"nmc.complaints.dlq.v1","count":1,"entries":[{"partition":0,"offset":0,
     "dlqReason":"invalid-envelope","detail":"missing or non-string sourceRecordId",
     "originalTopic":"water.sensors.raw.v1","raw":"{\"eventId\":\"evt-p10-dlq-probe\",…}"}]}

**6. Smoke test green over HTTPS** — OPERATIONS §11 steps 1–6, `SMOKE-RESULT: 6/6 PASS`, exit code
0 (G10.1). **7. Backups restore** — the Phase-5 drill (G5.5, `RESTORE-DRILL-VERIFIED`, 8/8 tables
+ canary row + role matrix). **8. Kyverno clean** — 6/6 ClusterPolicies ready, 157 PolicyReports /
1080 results with **34 fail, attributed by report namespace**:

    fails by REPORT namespace: {'kyverno': 32, 'nagar-system': 2}
    fails by policy:           {'require-nagar-labels': 10, 'require-pod-security-context': 24}

This is **not** "zero fails in any mission namespace": 2 of the 34 land inside `nagar-system`, a
mission namespace (labels `app.kubernetes.io/part-of=nagarvault`, `nagar.io/phase=1`), on
`Pod/sealed-secrets-controller-…` violating `require-nagar-labels`. The other 32 are the Phase-1
*baseline* policies against Kyverno's own workloads, which are deliberately outside the mission's
label/PSS conventions. The old "zero in any mission namespace" claim was found false by the
2026-10-03 audit; the 2 mission-namespace results were then **closed in G10.8** (commit `90cb2cb9`,
Phase-1 patch + mirror cycle, no policy change); the `kyverno` bundle namespace was then cut 34 → 12
in **G10.9** (commit `42cd7faa`, every live workload conforms), leaving 4 immutable-selector labels
+ 8 frozen superseded-ReplicaSet reports as the recorded residual.

**9. No Argo drift** — 16/16 Applications `Synced/Healthy`, `git status --porcelain` empty.

### G10.3 — Compose-remnant verification (ADR-013 §1)

The charter says "delete", but ADR-013 superseded ADR-004 for this substrate, so this is the
verification the rebuild turned it into. Raw output:

    tracked compose files:                              (none)
    compose files anywhere in the tree (excl. agentic/tmp + deploy/third_party): 0
    nagar-vault-backend/ (the charter's extra scope):   absent from the tree

The two files under `agentic/tmp/minio-src/` are the **upstream MinIO source tree** (Phase-3's
build input, `.gitignore`d) and the ones under `deploy/third_party/` are vendored operator
bundles — neither is mission Compose state. There is no Compose remnant to delete.

### G10.4 — Stray tracked `.env` audit

    tracked .env* :                    (none tracked)
    .env* on disk (excl. node_modules): 0

The charter's "several per-service `.env` files exist today" is a Day-0 observation that the
rebuild invalidated — every service reads its config from env vars injected by its manifest
(CONVENTIONS §6 precedence), so there is nothing tracked, nothing stray, and nothing to remove.
I-3 holds by construction: no plaintext secret exists anywhere in the tree.

### G10.5 — Nested `frontend/frontend/Dockerfile`

    tracked frontend/frontend paths:  (none)
    directories named frontend:       ./deploy/phases/07-app-ui/frontend

Already resolved by the rebuild (ADR-013 §2): exactly one frontend directory and one Dockerfile
for it. Nothing to fix. The per-service Dockerfiles that remain (12 tracked, all under
`deploy/phases/**`) are the **retained operator build recipes** of ADR-013 §3 — they are the
images this mission built and staged, not the legacy frozen ones, which stay deleted (I-10).

### G10.6 — README rewrite

See the commit; the landing page no longer describes Compose as the runnable path.

### G10.7 — Ledger flip

`docs/PHASES.md` Phase 10 → Complete, and `AGENTS.md` §7 refreshed (it still read "Phases 9–10 are
not yet implemented" after Phase 9 closed).

### G10.8 — Post-handover closure: the `nagar-system` `require-nagar-labels` violation

The repaired mission-scope check (verify-command 8) proved exit criterion 4's second half was
false in a **mission** namespace: 2 failing results on `Pod/sealed-secrets-controller` in
`nagar-system`, one per rule of `require-nagar-labels`. The bundle's Namespace was labeled at
Phase 1 but its pod template was not, so the controller was admitted before the ClusterPolicies
went live and kept running — the same latent-Phase-1-flaw class the cert-manager patch already
records (`01-substrate/cert-manager/cert-manager-patches.yaml`, item 3).

**The fix (Phase-1 subtree, git-only).** `sealed-secrets-patches.yaml` item 3 adds
`app.kubernetes.io/part-of: nagarvault` and `nagar.io/phase: "1"` to the pod template, the two
labels the policy evaluates, matching the sibling cert-manager/kyverno control-plane pods. **No
policy was edited, weakened or exempted:** `policies.yaml` is byte-identical to its pre-fix
revision (`git diff` empty) and the live `require-nagar-labels` `spec` compares equal to the
kustomize build; application-namespace enforcement is unchanged.

**The delivery (documented git → mirror → Argo flow; no direct `kubectl` workload edit, I-1).**
Commit `90cb2cb9` (the patch) → rebuild the bare payload from the worktree, because the mirror
serves the mission branch and `origin` is stale (150 commits behind) → build + push
`git-repo-mirror:phase10-4` to the internal registry (`localhost:35000`, the host-published port
that *is* `k3d-nagar.localhost:5000` inside the cluster) → commit `894661c6` bumping `newTag` →
apply the mirror subtree out-of-band (OPERATIONS §9.4 exception #4 / §12.16), never hand-editing the
live Deployment → `kubectl rollout status deploy/git-repo-mirror`. Argo read the new revision on its
next poll (`status.sync.revision` → `894661c6`), reported `OutOfSync`, auto-synced, and rolled the
controller.

**Verification (raw):**

```
$ kustomize build --load-restrictor LoadRestrictionsNone deploy/phases/01-substrate | …
sealed-secrets-controller  namespace=nagar-system
  template labels: {'app.kubernetes.io/part-of': 'nagarvault', 'nagar.io/phase': '1',
                    'name': 'sealed-secrets-controller'}   selector: {name: sealed-secrets-controller}
$ kubectl rollout status deploy/sealed-secrets-controller -n nagar-system
  deployment "sealed-secrets-controller" successfully rolled out
$ kubectl get pods -n nagar-system -l name=sealed-secrets-controller -o json | …labels
  sealed-secrets-controller-647b5bd59-vs9nb
    {'app.kubernetes.io/part-of': 'nagarvault', 'nagar.io/phase': '1'}
$ SCOPE='nagar-app nagar-platform nagar-observability nagar-system' <verify-command 8>
  failing policy results in nagar-app nagar-observability nagar-platform nagar-system = 0
  CMD8 mission EXIT=0
$ <verify-command 8 with SCOPE='kyverno'>
  failing policy results in kyverno = 32
  CMD8 kyverno EXIT=1                      # the check still fails when violations exist
$ kubectl get policyreport -A | fails by report namespace
  {'kyverno': 32}                          # the nagar-system 2 are gone
$ kubectl get applications -n nagar-system  → 16/16 Synced Healthy; live require-nagar-labels spec == git
$ sealed-secrets-controller           1/1 Ready, still unsealing (logs: reason 'Unsealed')
```

**The `kyverno` bundle namespace — deliberate decision.** The remaining 32 fails are the policy
engine's own four controllers (admission/background/cleanup/reports) in `kyverno`, failing
`require-nagar-labels` (8 results) and `require-pod-security-context` (24: missing resources and
restricted security context). They were admitted before the policies went live, like the
sealed-secrets pod. Excluding a controller's own namespace is **not** the policy's documented
intent: `policies.yaml`'s header states "no workload is exempted from any policy below", and the
only carve-outs are `kube-system{,public,node-lease}` plus the narrow Strimzi selector. A `kyverno`
exclusion would weaken enforcement for that namespace, so none was added; the 32 are left
**recorded as a control-plane residual**, not silently exempted. Repairing them is the same
three-part patch (labels + resources + restricted securityContext) on four deployments of the
policy engine itself, which is a separate Phase-1 change, not part of this closure.

**Effect on exit criterion 4.** The mission-namespace violation is **closed**: verify-command 8
prints `= 0` and exits 0, and cluster-wide fails are `{'kyverno': 32}`. The literal "zero Kyverno
violations" is therefore still unmet cluster-wide, but the shortfall is now entirely the policy
engine's own bundle namespace — **no mission namespace has a Kyverno violation.**

### G10.9 — The `kyverno`-namespace residual: conform what is safely conformable, record the rest

Enumerated live from the PolicyReports before touching anything: **32 fails, all on the policy
engine's own four controllers** — 8 `require-nagar-labels` (4 `check-part-of-label` + 4
`check-phase-label`) and 24 `require-pod-security-context` (12 `require-resources-limits` incl. the
Deployment/ReplicaSet `autogen-` forms, 12 `restrict-pod-security-context`), across 4 Deployments,
4 ReplicaSets and 4 Pods. The vendor pod templates carry `app.kubernetes.io/part-of: kyverno`, no
`nagar.io/phase`, no pod-level `securityContext`, and no CPU limits. The earlier in-tree claim that
the bundle "pods are natively restricted-compliant" was **wrong** and is corrected in
`kyverno/kustomization.yaml`.

**What conforms, and was fixed** (`kyverno-workload-patches.yaml`, Phase-1 subtree, commit
`42cd7faa`): the `nagar.io/phase: "1"` label, a pod-level `securityContext`
(`runAsNonRoot: true` + `seccompProfile: RuntimeDefault`), and CPU limits on all four controller
containers. That is **32 → 12** failing results. The 8 ReplicaSet fails and 12 of the 16 Pod fails
are gone; the new Deployments and new ReplicaSets now **pass every policy** (verified report-by-report).

**What is deliberately NOT fixed, and why.** `app.kubernetes.io/part-of: kyverno` is a Deployment
*selector* key on all four controllers **and a Service selector key on six Services**, including
`kyverno-svc` — the `failurePolicy: Fail` admission webhook Service. `spec.selector` is
**immutable**: a server dry-run patch confirms `spec.selector: field is immutable`, so the change
cannot be delivered by a git → Argo apply at all. Conforming it would require deleting and
recreating the policy engine's own Deployments (a transient admission outage — `failurePolicy:
Fail` on an admission webhook means a moment with no ready backend can block *all* pod/deployment
creates) plus rewriting six Service selectors. Per the mission's stop-short clause, that was not
forced. It is also self-consistent with the engine's own design: Kyverno's
generated `kyverno-resource-validating-webhook-cfg` `namespaceSelector` already **excludes its own
`kyverno` namespace**, i.e. the engine does not treat itself as a policy subject.

**The residual is now smaller and precisely characterised:** 4 Pod `check-part-of-label` (the
Deployment-owned selector label) and 8 frozen results on **superseded 0-replica ReplicaSets**
(created 2026-09-30, never re-scanned; the bundle sets `revisionHistoryLimit: 10` and the repo has
no counter-convention, so they are kept as rollback targets). Raw:

```
$ kubectl get policyreport -n kyverno  →  fails by policy/rule
  ('require-nagar-labels','check-part-of-label') 4      # the 4 Pods — selector label, not fixable in place
  ('require-pod-security-context','autogen-require-resources-limits') 4    # 4 stale ReplicaSets
  ('require-pod-security-context','autogen-restrict-pod-security-context') 4 # 4 stale ReplicaSets
$ new Deployments + new ReplicaSets + new Pods' check-phase/securityContext/resources  → pass
$ SCOPE='nagar-app nagar-platform nagar-observability nagar-system' <verify-command 8>
  failing policy results in nagar-app nagar-observability nagar-platform nagar-system = 0  (exit 0)
$ kubectl get policyreport -A | fails by namespace  →  {'kyverno': 12}
$ kubectl get applications -n nagar-system  →  16/16 Synced Healthy
$ engine still enforcing: a conformant-except-labels pod is DENIED
  require-nagar-labels / check-part-of-label + check-phase-label   (admission webhook validate.kyverno.svc-fail)
$ policies.yaml vs HEAD~2  →  (empty; no policy edited, weakened or exempted)
```

**Net effect on exit criterion 4.** Cluster-wide fails fall 34 → 12, and the remaining 12 are
confined to the policy engine's own namespace: 4 non-conformable selector labels and 8 frozen
reports on superseded ReplicaSets. Every **live** Deployment, ReplicaSet and Pod in `kyverno` now
conforms, and **no mission namespace has a violation.**

### G10.10 — Independent re-verification of the kyverno residual (both blockers) — 2026-10-04

The 12 remaining results were re-derived from live state rather than trusted from the previous
pass's prose. Both structural claims hold under direct test, and clearing the residual is out of
bounds by every available route.

**(a) The 4 Pod `check-part-of-label` fails are not deliverable by git → Argo.**
`app.kubernetes.io/part-of: kyverno` is a `spec.selector.matchLabels` key on all four controller
Deployments and a `spec.selector` key on six Services (`kyverno-svc`, `kyverno-svc-metrics`,
`kyverno-background-controller-metrics`, `kyverno-cleanup-controller`,
`kyverno-cleanup-controller-metrics`, `kyverno-reports-controller-metrics`). A live server dry-run
patch of the Deployment selector is rejected:

```
$ kubectl -n kyverno patch deploy kyverno-admission-controller --type=merge \
    -p '{"spec":{"selector":{"matchLabels":{…,"app.kubernetes.io/part-of":"nagarvault"}}}}' --dry-run=server
The Deployment "kyverno-admission-controller" is invalid:
* spec.template.metadata.labels: Invalid value: {…}: `selector` does not match template `labels`
* spec.selector: Invalid value: {…}: field is immutable                         exit=1
```

A positive control (a mutable-field patch on the same object) returns `patched`, exit 0, so the
dry-run exercises real server validation, not a blanket refusal. The value the rule wants
(`nagarvault`) is the *only* value the selector could take, so satisfying the rule in place is
impossible: it would require deleting and recreating the policy engine's own four Deployments (a
transient admission outage under `failurePolicy: Fail`) plus rewriting six Service selectors.
Out of bounds.

**(b) The 8 ReplicaSet fails are accurate for superseded 0-replica ReplicaSets and cannot be cleared
without destroying rollback targets.** The four failing scopes are the old ReplicaSets
(`…-7487bc75cf`, `…-7999749dc`, `…-5656b8ccf4`, `…-7d77c775df`), each `desired=0`, created
2026-09-30T19:13:17Z; the four live ReplicaSets (created 2026-10-03T18:00:47Z, `desired=1`) read
`fail=0 pass=5`. The old templates genuinely lack the pod-level `securityContext` and CPU limits the
rule requires (raw dump: `pod securityContext: {}`, container limits only `memory`), so the reports
are not stale *values* — they are correct for objects that still exist. Each PolicyReport carries an
`ownerReference` to its ReplicaSet, so it lives and dies with that ReplicaSet.

Clearing them is out of bounds by every route: (i) the ReplicaSets are controller-generated, not git
objects, so no git → Argo delivery exists for any patch to them (I-1); (ii) patching their templates
directly is a forbidden imperative mutation *and* would silently alter what `rollout undo` restores;
(iii) `revisionHistoryLimit: 0` on the Deployments would GC them through git → Argo, but it destroys
the documented rollback history (PHASES.md §3) — the exact disqualifier; the bundle ships
`revisionHistoryLimit: 10` (pinned by ADR-002) and the repo has no counter-convention. The
ReplicaSet pod template *is* server-mutable (a JSON-patch dry-run returns `patched`, exit 0), which
rules out immutability as the reason and leaves the real one: deleting or rewriting them destroys
rollback targets. They are kept.

**Verification at HEAD (raw):**

```
$ SCOPE='nagar-app nagar-platform nagar-observability nagar-system' <verify-command 8>
  failing policy results in nagar-app nagar-observability nagar-platform nagar-system = 0  (exit 0)
$ kubectl get policyreport -A | fails by namespace   ->  {'kyverno': 12}   (TOTAL 12)
$ kubectl get applications -n nagar-system           ->  16 Synced Healthy
$ policies.yaml blob = HEAD blob 6c760719            ->  git diff vs HEAD: 0 lines (untouched)
$ engine still enforcing: a conformant-except-labels pod is DENIED by check-part-of-label
  (admission webhook validate.kyverno.svc-fail)
```

**Net effect on exit criterion 4 (unchanged in substance, now independently witnessed).** No mission
namespace has a Kyverno violation; every live workload in `kyverno` conforms; the 12 residual results
are two structurally-blocked classes in the policy engine's own namespace, each with the exact test
above. No policy was weakened, disabled or exempted, and no rollback target was deleted.

### G11 — Known-gaps audit: accepted-by-design vs genuinely-open, and the poison-pill fix — 2026-10-04

Each of the eight recorded gaps was read against the ADR or doc section it cites, to separate a
genuine unresolved defect from a decision the repository deliberately took. Four are
**accepted-by-design** (changing them would contradict a recorded decision) and four are
**genuinely open**; one of the open four is a hard environmental bound, and the single
highest-severity in-scope defect was then fixed and re-proved live.

| Gap | Cited source | Classification |
|---|---|---|
| 2 kyverno residual | — | **Closed as far as the invariants allow** (G10.10): two independently verified structural blockers, out of bounds to clear |
| 3 7-day drift soak | — | **Genuinely open, environmental bound**: the substrate is ~3 days old, so the window cannot have elapsed; no code change can close it |
| 4 supply-chain controls | SECURITY §7 ("CI (per phase, **not yet built**)") | **Accepted-by-design**: §7 states the target state, not current behaviour; AGENTS §6.3 forbids documenting an aspiration as reality — the gap is the honest record |
| 5 sealed-secrets key backup | SECURITY §6 / OPERATIONS §7 | **Accepted-by-design**: the drill's key was shredded on purpose (disposable cluster); OPERATIONS §7 documents the offline-vault procedure a production posture would use |
| 7 disposable single-node substrate | ADR-006 ("single-node data plane **accepted** (with named mitigations)") | **Accepted-by-design**: explicit risk acceptance with named mitigations; not a defect |
| 8 Day grid not followed | MISSION.md §2 ("days are targets, not walls") | **Accepted-by-design**: the whole build executed in one continuous session with gates honoured in order; the "Day 7" label denotes the final phase, not seven elapsed days |
| 1 SLM table mis-targeting | ARCHITECTURE §3.4 ("the LLM has no direct database access") + SECURITY §3 | **Genuinely open, contained**: the generated SQL must pass queryService's AST + RBAC gate, and the observed failure produced a correct `403 table-rbac` — a quality issue, not a security hole. Deferred as a scope decision (product quality in `07-app-slm`), not a bound |
| 6 enrichWorker per-message death | ADR-029 ("the follow-up, deliberately not bundled") | **Genuinely open, high severity — FIXED in this pass** |

**Gap 6 reproduced live before touching anything.** ADR-029's "deeper issue" is a poison pill. An
`occurredAt` that `handle_message` accepts (it only checks the field is a non-empty *string*) but
PostgreSQL rejects (`timestamptz NOT NULL` column):

```
$ produce occurredAt="not-a-timestamp" to nmc.complaints.raw.restricted.v1
  -> psycopg.errors.InvalidDatetimeFormat: invalid input syntax for type timestamp with time zone:
     "not-a-timestamp"
     [the traceback escaped the loop; the offset is committed only AFTER process_message returns,
      so the same message was re-polled on every restart]
$ kubectl -n nagar-app get pods   ->  enrich-worker  RESTARTS 0 -> 1 -> 2 -> 3   (CrashLoopBackOff)
$ kafka-consumer-groups --describe --group enrichWorker
  nmc.complaints.raw.restricted.v1  16  16  1   (LAG 0 -> 1, member `-` = no live consumer
```

**The fix** (Phase-7c subtree, no policy or invariant touched): `process_message` wraps the DB write
and quarantines a **data-level** `psycopg.Error` to the DLQ, acknowledging the message, while
connection-level failures (`psycopg.OperationalError` / `InterfaceError`) still propagate — a database
outage is a readiness problem, not the message's fault. `OperationalError` does *not* cover data
errors (`InvalidDatetimeFormat` is a `DataError`, a sibling), so the guard is keyed on the base
`psycopg.Error` with the connection classes re-raised. Regression tests added (hermetic):
`test_data_level_db_error_is_quarantined_not_raised` and `test_connection_error_still_propagates`.

```
$ cd deploy/phases/07-app-worker/worker && python -m pytest -q    ->  24 passed
$ kustomize build deploy/phases/07-app-worker                    ->  exit 0  (image @sha256:152b1f14…, I-12)
$ kubectl apply --dry-run=server                                 ->  exit 0 (admitted by the same webhook)
$ shipped as mission/nagar-enrich-worker:phase7c-3 sha256:152b1f14… (registry-push header), digest pin updated
$ Argo nagar-phase7c-worker  ->  Synced Healthy @ be7ef1ab
```

**Re-proved against the real surface, not by reading.** The poison message was still queued (LAG=1)
when the fixed worker started, so the recovery is the operator-visible one:

```
$ kubectl -n nagar-app logs deploy/enrich-worker
  nmc.complaints.raw.restricted.v1 None -> db-error          (was: process death)
$ kubectl -n nagar-app get pods   ->  RESTARTS 0             (was: 3 and climbing)
$ kafka-consumer-groups --describe --group enrichWorker
  nmc.complaints.raw.restricted.v1  16  16  0   rdkafka-…   (LAG 0, member live)
$ kafka-console-consumer --topic nmc.complaints.dlq.v1
  {"dlqReason": "db-error", "detail": "InvalidDatetimeFormat: invalid input syntax for type
   timestamp with time zone: \"not-a-timestamp\"", "originalTopic": "nmc.complaints.raw.restricted.v1",
   "raw": "{\"eventId\":\"evt-g11-bad-ts\",…,\"occurredAt\":\"not-a-timestamp\",…}"}  (quarantined)
$ psql -d nagardb -tAc "SELECT count(*) FROM nmc_complaints WHERE event_id='evt-g11-bad-ts'"  ->  0
$ psql -d nagardb  5 dept counts  ->  complaints 14 | traffic 2 | water 2 | health 2 | ev 2
```

**Net effect.** Gap 6 is closed and the tier now survives a bad event the way ARCHITECTURE §3.3's
contract requires ("malformed events … never crash the loop"). The other three genuinely-open gaps
stay open for the stated reasons — gap 3 is an elapsed-time bound, gap 1 is a contained quality
ADR-gated follow-up — and the four accepted-by-design gaps were left exactly as their ADRs decided.

---

## Handover report (MISSION.md §5, Day 7 closure) — 2026-10-03

### What is deployed

Sixteen Argo CD Applications, **16/16 `Synced`/`Healthy`** at the time of writing, reconciled from
`deploy/phases/` through the in-cluster git mirror (ADR-014) onto one disposable single-node k3d
cluster (`k3d-nagar`, k3s v1.31.5+k3s1, age 2d21h). Everything below is live and was exercised by a
recorded gate, not merely applied:

| Tier | Live components | Phases |
|---|---|---|
| Substrate | 6 mission namespaces at PSS `restricted`; cert-manager; Sealed Secrets; Kyverno (3 baseline + full set); Traefik edge + internal CA | 1, 8, 9 |
| Data plane | MinIO StatefulSet + `raw-media`/`raw-sensitive-media`/`pg-backups`; Redis; Strimzi Kafka (KRaft, single node, 6 frozen topics on `kafka-bootstrap:29092`); CloudNativePG 2-replica `postgres` + migration Job + scheduled backups; Qdrant + Ollama (BGE-M3, Qwen3 1.7B) | 3, 4, 5, 6 |
| App tier | `authService:4000`, `adminService:4001`, ingestion `:3000`, `frontend:3001` (+ its BFF), `queryService:4003`, `slmService:4004`, `schemaIndexer:4005`, `enrichWorker` | 7a–7g |
| Observability | Prometheus, Loki, Grafana (authenticated), Alertmanager — 10/10 scrape targets up; one alert deliberately fired **and delivered to Alertmanager** carrying `runbook_url: docs/OPERATIONS.md#rb-12.1` | 9 |
| GitOps | Argo CD app-of-apps, `AppProject nagar` confined to the six mission namespaces, self-heal proven by reverting a manual mutation | 2 |

All images are pinned by digest (I-5) and are pulled from the internal registry by the cluster-side
mirror name; secrets exist only as SealedSecret blobs (I-3). Enforcement is not cosmetic: the
default-deny NetworkPolicies, PSS labels and Kyverno policies were each proven by a **negative**
probe that was actually denied.

### How to verify in 10 commands

Run from the repo root against the `k3d-nagar` context. Each line is a real check used by a phase
gate; expected output in the comment.

```bash
# 1  GitOps truth: every Application reconciled
kubectl get applications -n nagar-system                     # 16 rows, all Synced Healthy
# 2  nothing unhealthy anywhere (only Completed Jobs may appear)
kubectl get pods -A --field-selector=status.phase!=Running   # no Pending/CrashLoop/Error
# 3  the broker CR is Ready
kubectl get kafka nagar -n nagar-platform                    # READY True
# 4  the six frozen topic names exist (CONVENTIONS §4 / ARCHITECTURE §4.2)
#    --list also prints Kafka's internal __consumer_offsets, so expect 7 lines, not 6
MSYS_NO_PATHCONV=1 kubectl exec -n nagar-platform nagar-dual-role-0 -- \
  /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka-bootstrap.nagar-platform.svc.cluster.local:29092 --list
# 5  the warehouse is a healthy 2-replica CNPG cluster
kubectl get cluster postgres -n nagar-platform               # Instances 2, all Ready
# 6  the three frozen buckets exist on the storage layer. The MSYS guard is REQUIRED:
#    without it Git Bash rewrites /data to a Windows path and the command exits 1
MSYS_NO_PATHCONV=1 kubectl exec -n nagar-platform minio-0 -- ls /data
#    -> pg-backups  raw-media  raw-sensitive-media
# 7  every Kyverno policy is Ready
kubectl get clusterpolicy                                    # each READY=True
# 8  COUNT the FAILING policy results in a namespace scope and exit 1 if any exist.
#    (The previous version of this line, `... | grep -v PASS`, could never fail: measured,
#    0 of 133 mission-namespace report rows contain the literal "PASS", so the filter
#    removed nothing and the command exited 0 either way — found by the 2026-10-03 audit.)
#    Proof it can fail: SCOPE='kyverno' prints 32 and exits 1.
SCOPE='nagar-app nagar-platform nagar-observability nagar-system'
kubectl get policyreport -A -o json | SCOPE="$SCOPE" python -c '
import json,os,sys
ns=set(os.environ["SCOPE"].split()); n=0
for r in json.load(sys.stdin)["items"]:
    if r["metadata"]["namespace"] in ns:
        n += sum(1 for x in r.get("results",[]) if x.get("result")=="fail")
print("failing policy results in", " ".join(sorted(ns)), "=", n); sys.exit(1 if n else 0)'
#    -> 2026-10-03 audit result: "... = 2", exit 1 — both on Pod/sealed-secrets-controller in
#       nagar-system (CONVENTIONS §5). FIXED in G10.8 (commit 90cb2cb9); current result:
#       "... = 0", exit 0. The remaining cluster-wide fails (34 -> 12 in G10.9, commit 42cd7faa)
#       are the kyverno bundle namespace's own workloads: 4 immutable-selector labels + 8 frozen
#       superseded-ReplicaSet reports, recorded as a control-plane residual (gap 2).
# 9  the entry gate end-to-end over HTTPS (seed per OPERATIONS §5 first):
kubectl -n nagar-app exec deploy/auth-service -- \
  python seed_admin.py --username ops-check --user-id ops-check-001
NV_ADMIN_USER=ops-check NV_ADMIN_PASSWORD='<from line 2 above>' \
  python deploy/phases/10-parity-cutover/e2e/e2e-smoke.py    # SMOKE-RESULT: 6/6 PASS, exit 0
# 10 every manifest tree still builds (I-12)
for d in $(dirname $(find deploy -name kustomization.yaml)); do \
  kustomize build --load-restrictor LoadRestrictionsNone "$d" >/dev/null || echo "FAIL $d"; done
                                                             # silent: 41/41 trees PASS
```

### Known gaps

Recorded rather than buried. Each is a real limitation of the shipped state, not a formatting note.

1. **slmService table mis-targeting (open, out of Phase-10 scope).** Asked a *vague* question — "How
   many complaints are in the warehouse?" — Qwen3 1.7B sometimes answers against the wrong table.
   Observed at closure: `SELECT COUNT(*) FROM health_camp_records WHERE media_bucket IS NOT NULL`,
   which `nmc_officer` is correctly denied by `ROLE_TABLES` (SECURITY §3), so the officer got a
   correct **403 `table-rbac`**. The behaviour is per-sample non-deterministic at `temperature: 0`
   (1 fail in 4 identical runs — the retrieved context is what varies), which makes the model's
   *accuracy* a product-quality issue in `07-app-slm`, outside this phase's subtree (I-9). An
   operator will meet it; the blocked attempt is at least always visible in `audit_logs`.
2. **"Zero Kyverno violations" is not met cluster-wide, though no mission namespace is affected.**
   The 2026-10-03 audit's repaired check (verify-command 8) found **2 fails in `nagar-system`, a
   mission namespace**, on `Pod/sealed-secrets-controller`, failing `require-nagar-labels` for a
   missing `app.kubernetes.io/part-of`/`nagar.io/phase` (CONVENTIONS §5); the earlier reading had
   called all 34 "Kyverno's and Argo's own workloads … zero fails in any mission namespace", wrong
   and surviving only because the check written to support it could not fail. Those 2 were **fixed
   in G10.8** (commit `90cb2cb9`; verify-command 8 now prints `= 0`, exit 0). The `kyverno` bundle
   namespace was then reduced **34 → 12** in G10.9 (commit `42cd7faa`): the four controllers' pod
   templates gained `nagar.io/phase`, a pod-level `securityContext` and CPU limits, so every **live**
   Deployment, ReplicaSet and Pod in `kyverno` now conforms. The 12 that remain are 4 Pod
   `check-part-of-label` (the `part-of` value is an **immutable Deployment and Service selector**,
   not fixable in place) and 8 frozen reports on **superseded 0-replica ReplicaSets**. Excluding a
   controller's own namespace is *not* the policy's documented intent ("no workload is exempted"),
   so no exemption was added — the residual is recorded, not exempted. Both structural claims were
   **independently re-verified against live state in G10.10** (2026-10-04): the Deployment selector
   rejects the change as `field is immutable` under a server dry-run with a passing positive
   control, and the 8 ReplicaSet reports are owned by superseded `desired=0` ReplicaSets whose
   templates genuinely lack the required fields. Clearing them is out of bounds: no git → Argo path
   exists to a controller-generated ReplicaSet, and the only git-deliverable route
   (`revisionHistoryLimit: 0`) destroys rollback history.
3. **"No drift in Argo for 7 consecutive days" is not observable.** The substrate is 2d21h old, so
   the criterion cannot have been met by observation. What is proven: 16/16 `Synced`/`Healthy` now,
   and a self-heal test that reverted a manual mutation within ~30 s (G2.2).
4. **Supply-chain controls (SECURITY §7) are not implemented.** No image has a bystander SBOM, scan
   or signature; for the two *source-built* images (ADR-015) there is no upstream CVE backstop
   either. In force: digest pinning plus a build-time binary checksum gate (R8, first raised Phase 3).
5. **The Sealed Secrets controller key backup was ephemeral.** The Phase-1 round-trip drill exported
   the key to prove recovery, then shredded it on the disposable cluster. A production posture needs
   an offline vault, and OPERATIONS §7 documents the procedure that would use it.
6. **enrichWorker's per-message-death defect is CLOSED (was open; fixed in G11, 2026-10-04).**
   ADR-029 fixed the specific `media_bucket` bug and named the deeper one — a `psycopg` error in the
   consumer loop terminating the process — as the deliberate follow-up it did not bundle. G11
   reproduced it live (one `occurredAt` the DB rejected: `InvalidDatetimeFormat`, restarts 0 → 1 → 2 →
   3 CrashLoopBackOff, `nmc.complaints.raw.restricted.v1` LAG stuck at 1) and fixed it in
   `process_message`: a data-level psycopg error is now quarantined to the DLQ and the message
   acknowledged, while connection-level failures still propagate. Shipped as `phase7c-3`; re-proved
   live against the still-queued poison message — `-> db-error`, restarts 0, LAG 0, the message in the
   DLQ.
7. **The substrate is disposable and single-node.** k3d on one host, 16 GB RAM (Docker VM 8.17 GB),
   Kafka and MinIO single-node by risk acceptance (ADR-006). State lives on a host bind-mount, and the
   `~/.wslconfig` raise to 14 GB written on Day 0 is still **pending owner approval** (R1) — the
   mission completed without it. Host ports 3000–4005 are occupied, so the edge is reached by
   port-forward (R4), not by a published port.
8. **The Day grid was not followed in days.** MISSION.md §2 marks days as targets, not walls; the
   whole build executed in one continuous session with gates honoured in order, so the "Day 7" label
   on this report denotes the final phase, not seven elapsed days.

> **Status re-check (2026-10-04):** each of the eight gaps below was re-read against the doc/ADR
> section it cites and given a current status in **G12 — gap-ledger status re-check and verification
> sweep** (at the end of this journal). No accepted-by-design decision was rewritten there.

### Extension-sprint recommendations

In MISSION.md §2's priority order, with the two this session surfaced promoted where they belong:

1. **Close gap 1 — make the SLM reliably map intent to table.** Fix retrieval/prompt quality in
   `07-app-slm` and add a regression check for table choice. Highest value: it is the only gap an
   officer can trigger by accident.
2. **Close gap 3 — run a real 7-day drift soak.** Nothing else can turn that criterion green; a
   chaos/drift storm (kill pods, churn manifests, watch self-heal) both proves it and stresses the
   control plane.
3. **Multi-broker Kafka.** `KafkaNodePool/dual-role` is already split, so widening is a manifest
   edit rather than a migration (deliberate, per Phase 4).
4. **mTLS east-west** — needs an ADR first (every hop today trusts the cluster network).
5. **Load and restore drills** as routine, building on the Phase-5 restore drill (G5.5,
   `RESTORE-DRILL-VERIFIED`, 8/8 tables + canary row + role matrix).
6. **Supply-chain pipeline (gap 4)** — vendor `syft`/`trivy`/`cosign` the way every other tool was
   vendored, then gate the image builds on it.
7. **SLM tier performance tuning.** CPU-only inference is 10–30 s per query (R5, documented, not a
   defect); batching, model warm-keeping or a GPU node pattern would change it.

### Restart-from-scratch runbook

**Status: documented from the commands actually used, NOT re-executed end-to-end.** No phase rebuilt
the substrate from zero after Day 0, so MISSION.md §5's "ultimate zero-maintenance test" — a fresh
operator rebuilding everything from git + docs alone — has **not been performed**. Treat this as a
procedure with verified parts, not a verified procedure.

| Step | Command / reference | Verified when |
|---|---|---|
| 1. Tooling | `k3d` 5.8.3, `kubeseal` 0.28.0, `kustomize` 5.8.1, `kubectl` 1.36.1, Node 22, Python 3.12 | Day 0 audit |
| 2. Cluster + registry | `k3d cluster create nagar --servers 1 --image rancher/k3s:v1.31.5-k3s1 --registry-use nagar.localhost:35000 --volume C:\Users\<you>\.k3d\nagar-storage:/var/lib/rancher/k3s/storage@server:* --k3s-arg "--disable=traefik@server:0"` | G0.1 (note: the volume path must be **Windows-style**; an MSYS `/c/...` path is silently dropped) |
| 3. Registry round-trip | push via `localhost:35000`, pull in-cluster as `k3d-nagar.localhost:5000` | G0.2 (tag **and** digest) |
| 4. Substrate manifests | `deploy/phases/01-substrate/` + `deploy/third_party/` (vendored, ADR-002), applied server-side; build with `--load-restrictor LoadRestrictionsNone` | G1.1–G1.3 |
| 5. Secrets | re-seal the four SealedSecrets offline against the controller cert (`kubeseal --cert`), apply, verify `Synced=True`; recovery via `--recovery-unseal` + the exported controller key (OPERATIONS §7) | G1.2 (4/4 hashes) |
| 6. Git transport | build + push the `git-mirror` image, bump its **immutable** tag (`phaseN-M`, never reuse), wait for Argo | ADR-014; tag-reuse trap recorded in Phase 2 |
| 7. Argo bootstrap | server-side apply of the **whole** phase tree as one unit (a partial apply leaves `AppProject` missing and every child `InvalidSpecError`) | Phase 2, lesson 5 |
| 8. Data plane → app tier | phases 3→7 in dependency order; each phase's gate re-run from its mission-log section | G3.1–G7g.3 |
| 9. Edge, then observability | phase 8 (HTTPS smoke steps 1–2), then phase 9 (alert → Alertmanager, Kyverno probes) | G8.1–G8.7, G9.0–G9.8 |
| 10. Final gate | `python deploy/phases/10-parity-cutover/e2e/e2e-smoke.py` expected `6/6 PASS`, exit 0 | this report, three witnessed runs |

Reference docs the runbook leans on: `docs/OPERATIONS.md` (§1 install, §2 deploy, §5 seed, §7
backup/restore, §11 smoke, §12 troubleshooting matrix), `docs/SUBSTRATE.md` (k3d lifecycle: backup,
space reclaim, rebuild, restore, reseal), `docs/PHASES.md` (per-phase rollback doctrine).

---

### MISSION.md §6 exit criteria — assessment

Each criterion is quoted as written in §6 and marked with the evidence that decides it.

| # | §6 criterion | Status | Evidence |
|---|---|---|---|
| 1 | "Every phase 1–10 marked Done in the PHASES.md status ledger **with evidence links**" | **Met** | All rows 0–10 read `Done`/`Complete`, and every row now carries its own evidence reference in the ledger: each Status cell cites the mission-log gate range that decided it (`G1.1–G1.3` … `G10.0–G10.7`), with the 7a–7g row citing all seven micro ranges and pointing at §2 Phase 7's per-micro detail. The references are **textual, in the idiom §2 already uses** ("(G7a.1–G7a.7 in the mission log)") — this file has no hyperlink convention for internal evidence, and §0 item 5 fixes the table's shape, so no column was added. One honest exception is stated in the row rather than fabricated: Phase 0 has **no gate of its own** (G0.1–G0.3 cover cluster bring-up), so its row cites the Day-0 baseline commit `21472138` and mission-log §0.3. |
| 2 | "OPERATIONS §11 smoke script green over HTTPS on the cluster" | **Met** | Three consecutive witnessed runs 2026-10-03T16:06:33Z/47Z/53Z, each all six markers, `SMOKE-RESULT: 6/6 PASS`, exit code 0. Raw output in G10.1. |
| 3 | "Parity checklist fully signed, including RBAC enforced, PII denylist enforced, DLQ inspectable, backup restore drill succeeded, Argo drift-free" | **Met except one item** | G10.2: all 6 topics consumed (LAG 0 on all five raw topics), all 5 dept tables written, RBAC matrix enforced via the edge (admin/officer/no-JWT rows), PII denylist enforced (`pii-column` 403 + allowed control), DLQ inspectable (live malformed event → `nmc.complaints.dlq.v1` → `GET /admin/dlq` 200). **RBAC** additionally re-proven at closure by a *correct block* (gap 1). Backup restore drill succeeded in Phase 5 (G5.5). The one unmet item is **"no drift in Argo for 7 consecutive days"** — see gap 3. |
| 4 | "`kustomize build` clean across the whole `deploy/` tree; **zero Kyverno violations**" | **Met for mission namespaces; residual confined to the engine's own namespace** | First half **verified live**: 41/41 kustomization trees build clean, 0 failures. Second half: the audit found 34 fails, **2 in `nagar-system`, a mission namespace** (`Pod/sealed-secrets-controller`), **fixed in G10.8** (commit `90cb2cb9`) so verify-command 8 prints `= 0` and exits 0; the `kyverno` bundle namespace was then cut **34 → 12** in G10.9 (commit `42cd7faa`) and every **live** workload there now conforms. The 12 remaining are 4 non-conformable immutable-selector labels + 8 frozen reports on superseded ReplicaSets, all in `kyverno` — **no mission namespace has a violation**, no policy was weakened or exempted (gap 2). Both blockers were independently re-verified against live state in G10.10, and clearing the 8 ReplicaSet reports is out of bounds (no git → Argo path to a controller-generated ReplicaSet; `revisionHistoryLimit: 0` destroys rollback history). |
| 5 | "Compose files and per-service Dockerfiles deleted; legacy `.env` audit recorded; `frontend/frontend/` duplicate resolved" | **Met, with a documented deviation** | 0 tracked Compose files and 0 on disk; 0 tracked `.env` files; 0 `frontend/frontend/` paths with exactly one frontend directory (`deploy/phases/07-app-ui/frontend`) — all re-verified at HEAD for this report. Deviation: the **13** tracked Dockerfiles are *not* deleted — they are the **new** per-service build recipes the rebuild created (ADR-013 §3), retained deliberately; the legacy frozen ones were already gone (I-10). The charter's "delete" became "verify absence" under ADR-013. |
| 6 | "Doc suite updated to describe reality (no aspiration stated as fact)" | **Met** | `README.md` no longer describes Compose as runnable; `AGENTS.md` §7 says Phases 1–10 and calls the rebuild the shipped state; the §1 ledger and §2 charters agree (`c3589a39`). The last stale phrase is now gone too: Phase 10's skip-consequence cell reads **mandatory** (the cutover is what certifies the shipped state), matching §0 item 4's "mandatory" convention for phases 1, 7a and 10 and dropping the retired "transition" framing. |
| 7 | "All ADRs written; mission log complete; handover report delivered" | **Met** | 29 ADRs, numbering 001–029 contiguous (0 gaps), ADR-013 and ADR-027–029 written by this mission's rebuild and closure work. The log's per-phase sections carry commands + outputs for phases 0–10. This report is delivered as the journal's final entry, which is the location MISSION.md §5 prescribes for it. |

**Summary: 5 of 7 fully met (1, 2, 5, 6, 7); #3 is met except its 7-day drift item and #4 remains
partly met — no criterion is silently claimed.** Criteria 1 and 6 were the two documentation-sized
shortfalls and both are now closed: the ledger rows carry their evidence references, and the retired
"transition" framing is gone from the last place it survived. #4 improved at closure: the repaired
failure-count check found 2 failures in `nagar-system`, a mission namespace, and those were fixed in
G10.8 (commit `90cb2cb9`); the `kyverno` bundle namespace was then cut 34 → 12 in G10.9 (commit
`42cd7faa`), where every live workload now conforms. The 12 remaining are 4 non-conformable
immutable-selector labels and 8 frozen reports on superseded ReplicaSets, confined to the engine's
own namespace, deliberately not exempted (gap 2). G10.10 (2026-10-04) re-verified both blockers
against live state — the selector rejects change as `field is immutable` under server dry-run, and
the 8 ReplicaSet reports are owned by superseded `desired=0` ReplicaSets — and confirmed the
residual is not clearable through git → Argo without destroying rollback history. Two criteria have
*observational* limits that no code change can close: the 7-day drift window (cluster is 2d21h old)
and the unproven restart-from-scratch runbook.

---

## G12 — Gap-ledger status re-check and verification sweep — 2026-10-04

Appended after G11's audit. **No accepted-by-design decision is rewritten, no policy is weakened,
and no ADR is added** — this section records what each of the eight gaps *is now*, the doc/ADR
section it rests on, and the fresh evidence gathered from a host that **started the sweep with no
cluster access and no running Docker engine**. Every in-cluster or daemon-dependent check is either
run for real once Docker Desktop (and with it the `k3d-nagar` cluster) came back up, or marked
**unverifiable from this host** — never simulated.

### Gap status now

| Gap | Status now | Rests on |
|---|---|---|
| 1 SLM table mis-targeting | **Code-complete and SHIPPED to the registry** (`phase7d-3`, digest pinned, pull-verified in-cluster). The running Deployment still reads the previous digest until the updated pin reaches the git mirror and Argo reconciles. | ARCHITECTURE §3.4 + SECURITY §3 (the generated SQL still has no database access of its own and must pass the queryService gate) |
| 2 kyverno residual | **Unchanged, recorded not exempted**: 4 non-conformable immutable-selector labels + 8 frozen reports on superseded `desired=0` ReplicaSets, all confined to the `kyverno` bundle namespace; no mission namespace affected. | G10.9 / G10.10; CONVENTIONS §5 |
| 3 7-day Argo drift soak | **Open, environmental bound**: the substrate is ~3 days old, so the window cannot have elapsed; no code change closes it. | MISSION.md §6 criterion 3 |
| 4 supply-chain controls (SBOM / scan / sign) | **Accepted-by-design, target state**: §7 states *"CI (per phase, not yet built)"*, so this records the target, not a current behaviour. | **SECURITY §7** |
| 5 sealed-secrets controller key backup | **Accepted-by-design**: the drill's key was shredded on purpose on the disposable cluster; the offline-vault procedure a production posture would use is documented. | **SECURITY §6 / OPERATIONS §7** |
| 6 enrichWorker per-message death | **CLOSED and RE-CONFIRMED this pass** (see below). | ADR-029 + ARCHITECTURE §3.3 |
| 7 disposable single-node substrate | **Accepted-by-design**: single-node Kafka/MinIO is an explicit risk acceptance with named mitigations; the `.wslconfig` 14 GB raise is still pending owner approval (R1). | **ADR-006** |
| 8 "Day grid" not followed | **Not a defect**: days are targets, not walls; gates were honoured in order in one continuous session. | **MISSION.md §2** |

### Gap 6 — re-confirmed (evidence only, no code change)

The guard read in `deploy/phases/07-app-worker/worker/enrich.py`:

* `DB_CONNECTION_ERRORS = (psycopg.OperationalError, psycopg.InterfaceError)` — connection-level
  failures, re-raised so a database **outage** is not drained into the DLQ.
* `process_message(topic, raw) -> "upserted" | "db-error" | "dlq"` wraps the DB write; a **data-level**
  `psycopg.Error` (any non-connection psycopg error) clears the upserts, quarantines the message to
  `nmc.complaints.dlq.v1` and lets it be acknowledged, so one bad event can no longer become a
  poison-pill CrashLoopBackOff.

The two regression tests named in G11 are present and pass:

```
$ cd deploy/phases/07-app-worker/worker && python -m pytest tests -q      ->  24 passed in 0.51s   (exit 0)
$ python -m pytest tests -q -k "quarantined or propagates"                ->  2 passed, 22 deselected (exit 0)
      test_data_level_db_error_is_quarantined_not_raised
      test_connection_error_still_propagates
```

### Gap 1 — code-complete, deterministic test green, image shipped

The prompt/retrieval fix landed in `deploy/phases/07-app-slm/slm/app.py` (Phase-7d subtree, I-9):
`qdrant_search` now surfaces each hit's `table`, `build_prompt` labels every context block
(`[table: <name>]` / `[schema overview]`), the prompt carries an explicit **choose-one-table-from-context**
rule plus a `` `-- no relevant table` `` sentinel instead of guessing, and `TOP_K` rose 5 → 8 so the
target table's docs stay in context. Untouched: the `/ask` flow, JWT inheritance, `extract_sql`, the
port (4004) and the queryService AST/RBAC gate — generated SQL must still pass that gate. No port,
topic, bucket or table changed, so no ADR is required.

```
$ cd deploy/phases/07-app-slm/slm && python -m pytest tests -q   ->  24 passed  (21 before; +3 regression tests)
$ kustomize build deploy/phases/07-app-slm                        ->  exit 0   (I-12)
```

**Ship step completed in the same pass once the Docker engine was started.** The engine was down at
the start of the sweep; Docker Desktop was launched, which restored the daemon and the `k3d-nagar`
cluster's registry container (`k3d-nagar.localhost`, `registry:2`, `localhost:35000`), after which the
image was rebuilt, pushed, digest-pinned and pull-verified:

```
$ docker build --provenance=false --sbom=false -f deploy/phases/07-app-slm/slm/Dockerfile \
    -t localhost:35000/mission/nagar-slm-service:phase7d-3 deploy/phases/07-app-slm      ->  exit 0
$ docker push localhost:35000/mission/nagar-slm-service:phase7d-3
  phase7d-3: digest: sha256:c4bfbb09732e893c00f50e107dbde8376165c7ab2570c700c79a3c5d76ca2085 size: 1812
$ curl -sI -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
    http://localhost:35000/v2/mission/nagar-slm-service/manifests/phase7d-3
  Content-Type: application/vnd.oci.image.manifest.v1+json
  Docker-Content-Digest: sha256:c4bfbb09732e893c00f50e107dbde8376165c7ab2570c700c79a3c5d76ca2085   (agrees with
    `docker image inspect … RepoDigests`)  — a single manifest, not an index: unambiguous to pin
$ kustomize build deploy/phases/07-app-slm   ->  exit 0; renders
  image: k3d-nagar.localhost:5000/mission/nagar-slm-service@sha256:c4bfbb09732e893c00f50e107dbde8376165c7ab2570c700c79a3c5d76ca2085
$ kubectl apply --dry-run=client -k deploy/phases/07-app-slm   ->  exit 0  (service/deployment/PDB/netpol configured)
$ kubectl apply --dry-run=server -k deploy/phases/07-app-slm   ->  exit 0
$ docker exec k3d-nagar-server-0 crictl pull \
    k3d-nagar.localhost:5000/mission/nagar-slm-service@sha256:c4bfbb09…  ->  exit 0  (registry round-trip, I-11)
```

The pin in `deploy/phases/07-app-slm/digest-pins/kustomization.yaml` now resolves to `phase7d-3`
(`sha256:c4bfbb09…`), replacing the superseded `phase7d-2` (`sha256:c83f6435…`).

**Not yet reconciled to the cluster (I-1).** The live Deployment still pins the previous digest
(`k3d-nagar.localhost:5000/mission/nagar-slm-service@sha256:c83f6435…`); the new pin is committed to
git but **not pushed to the in-cluster git mirror**, so Argo has nothing new to reconcile. No
imperative apply or rollout was used — cluster state must arrive from git. Until the pin is pushed,
the cluster still runs the previous SLM prompt even though the new image is in the registry and
pullable.

### Verification sweep run this pass (from this host)

| Check | Command | Result |
|---|---|---|
| Kustomize trees (I-12) | `kustomize build --load-restrictor LoadRestrictionsNone` over every `deploy/**/kustomization.yaml` | **41/41 build, 0 fail** |
| Worker suite | `python -m pytest tests -q` (`07-app-worker/worker`) | **24 passed**, exit 0 |
| Admin suite | `python -m pytest tests -q` (`07-app-admin/admin`) | **14 passed**, exit 0 |
| Auth suite | `python -m pytest tests -q` (`07-app-auth/auth`) | **22 passed**, exit 0 |
| Query suite | `python -m pytest tests -q` (`07-app-query/query`) | **29 passed**, exit 0 |
| SLM suite | `python -m pytest tests -q` (`07-app-slm/slm`) | **24 passed**, exit 0 |
| Ingestion suite | `node --test tests/ingestion.test.js tests/presign-url.test.js` | **10 pass / 0 fail**, exit 0 |
| Frontend BFF suite | `npm test` (`07-app-ui/frontend`) | **7 pass / 0 fail**, exit 0 |
| vault-ui proxy suite | `node --test tests/proxy.test.mjs` (`07-app-ui/vault-ui`) | **5 pass / 0 fail**, exit 0 |

The ingestion suite has **no `npm test` script**; the canonical invocation is the one G7e used
(`node --test tests/ingestion.test.js tests/presign-url.test.js`). Note that `node --test tests/`
(a bare directory argument) fails on Node 22 with `Cannot find module '…/ingestion/tests'` + `not ok 1
tests` — that is a runner-invocation artefact, not a suite failure; the same two files pass 10/10 when
named explicitly.

**Cluster reached later in the same pass.** Docker Desktop coming up also restarted the `k3d-nagar`
cluster, so the `kubectl apply` dry-runs and the registry round-trip above were run for real (they had
been unverifiable earlier in the sweep, when only `kustomize build` was possible). One environment
wrinkle, recorded because it will bite the next operator: the kubeconfig's
`server: https://host.docker.internal:62398` does not resolve to the load balancer from this host, so
the in-cluster checks were run against `--server=https://127.0.0.1:62398 --insecure-skip-tls-verify=true`
(the LB publishes on `0.0.0.0:62398`).

**Still unverifiable from this host (not run, not simulated):** the Argo 7-day drift soak, the
OPERATIONS §11 smoke (needs the seeded admin), and the in-cluster e2e suites. Separately, the new pin
is **not yet reconciled** — see the ship note above.

**Net effect.** Gap 6 is re-confirmed closed. Gap 1 is code-complete with its deterministic regression
tests green, and the image is **built, pushed, digest-pinned and pull-verified in-cluster**
(`phase7d-3`); the running Deployment still reads the previous digest until the updated pin is pushed
to the git mirror and Argo reconciles, so the cluster does not yet execute the new prompt. Gaps 2, 3,
5, 7 and 8 keep the status G11 assigned them; gap 4 remains the SECURITY §7 target state. No
accepted-by-design decision was rewritten and no ADR was added.


---

## G13 — Independent audit pass: the PII denylist had a whole-row hole (2026-10-05)

Requested scope: review, audit and fix. Every finding below was reproduced with a command
before any code changed; nothing here is asserted from reading.

### G13.1 Baseline audit — what was already sound

| Check | Command | Result |
|---|---|---|
| I-12 kustomize | `kustomize build --load-restrictor LoadRestrictionsNone` over every tracked tree | **41/41 build, 0 failures** |
| I-5 digest pins | grep of rendered `image:` for `@sha256`, all trees | **0 unpinned** (`deploy/third_party/**` excluded: upstream manifests) |
| I-3 secrets | grep for literal secret material | SealedSecret ciphertext + test fixtures only |
| I-4 shape | rendered probes/resources/PDB vs replicas | no violations (Jobs and vendored controllers excluded; enrich-worker's startup+liveness-only consumer pattern is a documented exception) |
| I-6 ports | rendered Service/containerPort census vs CONVENTIONS §4 | **1 first-party gap: 9418**; the rest are vendored controllers (Kyverno, cert-manager, Argo CD, CNPG) |
| Tests | pytest x5, `node --test` x3 | **142 pass, 0 fail** |

So the platform was structurally clean. The defects were logical, not structural — which is
exactly what a static audit misses and a behavioural probe finds.

### G13.2 The finding: whole-row reference defeated the PII denylist

`queryService`'s denylist (SECURITY §3 layer 4) matched denylisted **column names**. A query
that references the PII table itself contains no denylisted identifier, so it passed:

```
$ cd deploy/phases/07-app-query/query && python -   # probe against the shipped gate
SELECT c FROM nmc_complaints c            -> ALLOWED   # returns name/phone/email/address/aadhaar
SELECT nmc_complaints FROM nmc_complaints -> ALLOWED
SELECT to_jsonb(c) FROM nmc_complaints c  -> ALLOWED
SELECT row_to_json(c) FROM nmc_complaints c-> ALLOWED
SELECT to_jsonb(c.*) FROM nmc_complaints c -> ALLOWED
SELECT json_agg(c) / array_agg(c)          -> ALLOWED
SELECT name FROM nmc_complaints           -> BLOCKED(pii-column)   # the only shape that was caught
```

**There was no second line of defence.** Migration 001 grants `SELECT` at *table* level:

```
$ grep -n "GRANT SELECT" deploy/phases/05-postgres/migrations/001_create_tables.sql
229:GRANT SELECT ON nmc_complaints, traffic_events, water_sensor_readings, ev_bus_telemetry
```

so under `SET ROLE nmc_officer` the database would return every column. One application-layer
name-matcher stood between an `nmc_officer` JWT and citizen PII.

### G13.3 Also found

- **CTE handling (F2).** `find_all(exp.Table)` counted CTE *aliases* as tables. Legitimate
  queries were falsely blocked (`WITH recent AS (SELECT ward FROM nmc_complaints) SELECT
  count(*) FROM recent` -> `blocked(table-rbac)`), while a CTE named after an allowlisted
  table smuggled a data-modifying statement past the gate.
- **Upload-intent IDOR (F3).** `GET /api/v1/uploads/:id` returned the intent — bucket,
  objectKey and the minting `subject` — to any authenticated caller.
- **No query cost bound (F4).** `SELECT pg_sleep(60)` passed the gate; nothing stopped a
  legal-but-expensive query pinning a connection.
- **Port 9418 unregistered (F5)** and **`edge-minio` commented "PUT route ONLY"** when a
  Traefik IngressRoute cannot filter by method (F6) — an aspiration stated as fact.
- **schemaIndexer had no tests (F7)** — the only first-party component with none.

### G13.4 The fix, and proof that it fixes something

Layer 1 (shape gate): the projection must now be *proven column-by-column*. A reference to a
PII table or any alias of it is blocked, as is any `*` over a PII table anywhere; the only
exemption is an argument of a scalar-collapsing aggregate (`count`, `sum`, `avg`, ...), which
preserves the `COUNT(*)` carve-out the Phase-7d E2E needed. Serialising wrappers are
deliberately not exempt.

Layer 2 (backstop): `002_pii_column_grants.sql` revokes the table-level grant and grants
`SELECT (<every non-PII column>)`, derived from `information_schema` so it cannot drift.
An `InsufficientPrivilege` denial is now an audited `403 db-wall`, not a `503`.

**A regression test that passes on the broken code is worthless, so each was run against the
old gate** (restored from `HEAD` with the new tests left in place):

```
$ git show HEAD:…/query/app.py > app.py && python -m pytest tests -q
FAILED test_whole_row_reference_over_pii_table_is_blocked[SELECT c FROM nmc_complaints c]
FAILED …[SELECT to_jsonb(c) …] …[row_to_json(c) …] …[to_jsonb(c.*) …] …[json_agg(c) …]
FAILED …[array_agg(c) …] …[string_agg(c::text, ',') …] …[c.* …] …[(nmc_complaints).name …]
FAILED test_legitimate_queries_still_pass_the_gate[WITH recent AS …]
FAILED test_dml_hidden_in_a_cte_is_blocked
FAILED test_insufficient_privilege_is_reported_as_a_block
FAILED test_statement_timeout_is_reported_as_a_block
FAILED test_connections_carry_a_statement_timeout
16 failed, 39 passed          # EXIT=1
```

and the IDOR test against the old ingestion backend:

```
$ node --test tests/ingestion.test.js
not ok 8 - HTTP: an upload intent is readable only by the officer who minted it
# pass 7  # fail 1
```

With the fix in place: queryService **55 passed** (was 29), ingestion **12 passed** (was 11),
schemaIndexer **10 passed** (was 0 — none existed).

One audit finding was my error, not the code's: 11 documents in `schema_docs.json` have
`table: null`, which looked like missing attribution. They are the overview/sql-style docs
that slmService deliberately renders as `[schema overview]`. The test now asserts the real
contract — the key exists, and may be null — rather than a truthiness check that would have
"fixed" correct behaviour.

### G13.5 Not done in this pass

- **The ship step did not run.** The Docker daemon is down and the k3d cluster is
  unreachable, so no image was rebuilt, no digest pinned, nothing pushed, and Argo did not
  reconcile. The `002_pii_column_grants.sql` backstop and the corrected gate are in git but
  **not yet running anywhere**; the running Deployment still executes the old gate. Reported,
  not simulated (MISSION §4.3).
- No push to `origin`.


### G13.6 The backstop executed against a real PostgreSQL — and found a worse bug

Docker Desktop was started and the daemon answered (29.8.1), which also brought the k3d
cluster back with it. The project's own pinned operand image was pulled from the k3d registry
(`localhost:35000/mission/cnpg-postgresql:15.17-system-trixie`, digest
`sha256:0e1a5a4e…`) and run as a scratch PostgreSQL **15.17** — the same major version the
cluster pins — because the CNPG operand image has no stock entrypoint and needs
`initdb`/`postgres` invoked by hand.

```
$ docker exec pg002 bash -c 'cd /migrations && psql -X … -f 001_create_tables.sql'   -> exit 0
$ … -f 002_pii_column_grants.sql
NOTICE:  nmc_complaints: table-level SELECT revoked, 13 non-PII columns granted        -> exit 0
```

**The hole, at the database layer, with real data** (`Asha Verma / +91-98765-43210 /
asha@example.in / 123456789012` inserted first):

```
pre-002, SET ROLE nmc_officer; SELECT name, phone, email, aadhaar FROM nmc_complaints;
    name    |      phone      |      email      |   aadhaar
 Asha Verma | +91-98765-43210 | asha@example.in | 123456789012     <-- the exfiltration
```

**After 002**, for BOTH `nmc_officer` and `health_officer`:

```
PII name/phone/email/address/aadhaar -> ERROR: permission denied for table nmc_complaints
non-PII ward, status, description    -> W1|open|drain blocked
count(*)                             -> 1
SELECT *                             -> ERROR: permission denied for table nmc_complaints
```

Idempotency (I-2): run twice more, both `exit 0`, `information_schema` table-privilege
snapshot byte-identical across all three runs, 26 column-privilege rows (13 columns x 2
roles). Blast radius: `traffic_events`, `water_sensor_readings`, `ev_bus_telemetry` keep
their table-level grants for both roles and `health_camp_records` remains health-only, so
the SECURITY §3 role matrix is unchanged.

**Then queryService was run against that same database, and it failed a case** — the one that
mattered:

```
DB denies what AST allowed -> HTTP 200 [{'ward': 'W1'}]      <-- the wall was not applying
```

`current_user` at query time was **`postgres`**, not `nmc_officer`. `wall_begin` issued
`SET ROLE` on a connection it closed immediately, and `run_query_rows` opened a fresh one.
In production that role is `nagar`, which **owns** every warehouse table, so the whole SET
ROLE wall (SECURITY §3 layer 3, ADR-019) had never been in force — and 002's column grants,
which an owner bypasses, would have blocked nothing either. The AST gate was the only
control actually enforcing anything.

Fixed by putting `SET ROLE`, the statement and `RESET` on one connection. The first version
still returned 503: `RESET ROLE` in a `finally` runs inside the aborted transaction and
raises `InFailedSqlTransaction`, masking the `InsufficientPrivilege`. `RESET` now sits on
the success path only. Re-run, all ten end-to-end assertions pass:

```
PASS  legal non-PII query                 HTTP 200  [{'ward': 'W1', 'status': 'open'}]
PASS  DB denies what AST allowed          HTTP 403  {'reason': 'db-wall', 'verdict': 'blocked'}
PASS  recovered after re-grant            HTTP 200  [{'ward': 'W1'}]
PASS  PII column -> AST gate              HTTP 403  {'reason': 'pii-column', 'verdict': 'blocked'}
PASS  whole-row to_jsonb -> AST gate      HTTP 403  {'reason': 'pii-column', 'verdict': 'blocked'}
PASS  whole-row SELECT c -> AST gate      HTTP 403  {'reason': 'pii-column', 'verdict': 'blocked'}
PASS  star -> AST gate                    HTTP 403  {'reason': 'pii-column', 'verdict': 'blocked'}
PASS  COUNT(*) carve-out                  HTTP 200  [{'count': 1}]
PASS  non-PII table unaffected            HTTP 200  []
PASS  nmc_officer denied users            HTTP 403  {'reason': 'table-rbac', 'verdict': 'blocked'}
```

Full sweep after the change: query 57, worker 27, slm 24, auth 22, admin 14, indexer 10
passed; ingestion 12, frontend 10, vault-ui 5 passed; 41/41 kustomize trees build.

**Lesson worth carrying:** the hermetic suite passed 55 tests while the database wall was
silently inert, because the seam was mocked. Only running the real service against a real
database exposed it. A mocked seam proves the code calls the seam, not that the seam works.


### G13.7 Shipped: the fix is now the running system

Run through the sanctioned transport only (ADR-018 §9.4/§12.16) — no imperative resource
edits. Images built from these trees, pushed to localhost:35000, digests read from the
registry header and matched against the push output:

```
nagar-query-service:phase7b-3  sha256:398b5f52f1a91de7…   (was 7c70081f…)
nagar-ingestion:phase7e-6      sha256:acb0d7984af1f828…   (was d43961d6…)
git-repo-mirror:phase13-3      sha256:08697df07f02e3af…  (payload = repo @ 45d0b366)
```

The mirror payload was staged with `git clone --bare` at a byte-identical HEAD, and the
transport advanced with `kustomize build …/git-mirror | kubectl apply --server-side
--force-conflicts`. Argo picked the revision up on poll 8 (≈2 min) and every one of the 16
Applications reports **Synced / Healthy at 45d0b366**.

The migration Job replayed both files on the real cluster:

```
$ kubectl logs -n nagar-platform job/nagar-db-migrate
applying /migrations/001_create_tables.sql
applying /migrations/002_pii_column_grants.sql
NOTICE:  nmc_complaints: table-level SELECT revoked, 13 non-PII columns granted
migrations complete
```

Verified in the cluster's own `nagardb`: **26 column-privilege rows** (13 columns x 2 roles).
Live service, real `nmc_officer` token, 15 complaints in the table:

```
403  PII column (name)        {"reason": "pii-column", "verdict": "blocked"}
403  PII column (phone)       {"reason": "pii-column", "verdict": "blocked"}
403  whole-row SELECT c       {"reason": "pii-column", "verdict": "blocked"}
403  whole-row to_jsonb(c)    {"reason": "pii-column", "verdict": "blocked"}
403  star SELECT *            {"reason": "pii-column", "verdict": "blocked"}
200  non-PII (ward,status)    [{"ward": null, "status": null}, …]
200  COUNT(*)                 [{"count": 15}]
```

Note on the two layers: on the live cluster the AST gate blocks PII first, so the `db-wall`
branch is not reached for those queries. That branch was proven to answer **403 db-wall, not
503**, against the real 001+002 schema on the scratch instance; it is the same code path. It
was not forced on the cluster, because doing so would mean revoking a grant on production
data purely to make a branch execute.

`nagar-phase9-observability` was still Progressing at this point because
`nagar-kafka-exporter` was in CrashLoopBackOff (58 restarts, pod age 3d20h). Diagnosed and
fixed in G13.8 below.


### G13.8 kafka-exporter: the missing half of a NetworkPolicy

```
$ kubectl logs -n nagar-observability deploy/nagar-kafka-exporter --previous
F1005 15:47:05 kafka_exporter.go:901] Error Init Kafka Client: kafka: client has run out of
available brokers to talk to: dial tcp 10.43.74.110:29092: connect: connection refused
```

Ruled out by probe, in order, rather than by reading the manifest and guessing:

| Hypothesis | Probe | Result |
|---|---|---|
| Broker down / not listening | `/proc/net/tcp` in `nagar-dual-role-0` | **29092 IS listening** |
| Bootstrap Service broken | endpoints + `enrich-worker` connect to `10.43.74.110:29092` and `10.42.0.52:29092` | **both OK** |
| Exporter egress rule wrong | `allow-kafka-exporter-egress` selects the pod's real labels; ns label present | **rule is correct** |
| netpol not enforced at all | `nagar-alloy` → `10.43.74.110:29092` | **BLOCKED — netpol IS enforced** |

That left the one direction nobody had checked: NetworkPolicy is evaluated on **both** ends of
a connection. Phase 9 gave the exporter an egress rule; `allow-kafka-ingress` (Phase 4) still
admitted only intra-namespace pods and `nagar-app`. The broker's ingress half was never
widened, so the exporter could never have worked — it has been crash-looping since it was
created, and `nagar-phase9` has been Progressing for the whole project.

The peer added is namespace **and** pod scoped:

```yaml
- namespaceSelector:
    matchLabels:
      kubernetes.io/metadata.name: nagar-observability
  podSelector:
    matchLabels:
      app.kubernetes.io/name: nagar-kafka-exporter
```

A bare `namespaceSelector` would have admitted Grafana, Loki, Alloy and Prometheus to the
broker — flows none of them has. Same class as OPERATIONS §12.19, which is why the §8 flow
list now names the exporter and states the both-sides rule.

Shipped the same way as everything else (no imperative edits): commit → mirror payload at a
byte-identical HEAD → `phase13-4` → transport advanced server-side → Argo. Result:

```
$ kubectl logs -n nagar-observability deploy/nagar-kafka-exporter
I1005 15:57:17 kafka_exporter.go:971] Listening on HTTP :9308      # no init error
$ … wget -qO- http://127.0.0.1:9308/metrics | grep ^kafka_brokers
kafka_brokers 1
```

**All 16 Applications now report Synced + Healthy** — first time in this mission — and all
7 observability pods are 1/1 Running.

### G13.9 A TTL on an Argo-managed Job was a re-run trigger, not retention

Resumed after a host restart (Docker daemon down, so the k3d cluster was down). Everything
converged on its own: node Ready, CNPG `postgres` 2/2 healthy with `postgres-1` primary, every pod
Running or Completed. The kafka-exporter was crash-looping again, but only because its last
attempt (05:10:33) predated the broker finishing its own startup — its backoff had already grown
past the point where Kafka was listening. Cleared the pod; it came up 1/1 and Prometheus reports
the target up with `kafka_brokers 1`. G13.8's fix is intact at the live surface.

Then `nagar-phase6-vector-llm` reported `OutOfSync` with its Job missing, and the cause was not
what the record said. Watched directly:

```
[05:13:46] app=OutOfSync/Healthy  job=nagar-ollama-models NotFound
[05:14:32] app=OutOfSync/Healthy  job=nagar-ollama-models NotFound
[05:14:47] app=Synced/Progressing job=nagar-ollama-models Running 5s
```

Argo re-created the Job **at an unchanged revision**, and it re-ran end to end — checksum
verification of all nine model blobs, then `restoring into the shared PVC`: a multi-GB write into
the claim the live Ollama server reads. `ttlSecondsAfterFinished` deletes the completed Job
**object**; the desired object is then absent, which is drift Argo *can* see; `selfHeal: true`
recreates it; the Job re-runs. Five Argo-managed Jobs carried a TTL (bucket-init and
nagar-kafka-topics 24 h, nagar-db-migrate 1 h, nagar-ollama-models and nagar-schema-index 2 h), so
the loop was platform-wide and its period was simply the TTL. Corroborated by orphaned `Completed`
pods whose owning Job is gone (`nagar-ollama-models-lb6kx` 14 h, `nagar-db-migrate-fxt4k` 13 h,
`nagar-schema-index-xgf2d` 14 h). Argo's auto-sync backoff is what makes this look intermittent
rather than clockwork — which is also why a single `Synced` snapshot had looked fine before.

This **supersedes ADR-016 §1** ("is not re-run on syncs where the spec is unchanged … does not
churn (I-2)") and **re-attributes** the Phase-4 open item that blamed `Replace=true`: TTL alone is
sufficient, and it was the live cause. Removed from all five (ADR-032); `restore-drill/` keeps its
TTLs because that tree is deliberately not Argo-managed.

One more thing the ship exposed, worth having on the record:

```
$ kubectl get applications -n nagar-system            # after the mirror advanced to b6bab49
nagar-phase3-object-cache  Synced  Healthy            # …all four affected apps Synced
$ kubectl get jobs -n nagar-platform -o json | … 'ttlSecondsAfterFinished' in .spec
jobs with a live TTL: 5                                # …every live Job still carried one
```

Argo's differ does not compare `ttlSecondsAfterFinished`, so a git-side removal **never converges
on a Job that already exists** — the controller logged `Skipping auto-sync: application status is
Synced` while git and the cluster disagreed. Live state was brought to git state with the
sanctioned §8 pattern (delete the Job, let Argo recreate it): all five came back from the TTL-free
revision, re-ran idempotently (`INDEX-SYNC-OK`, 40 points), and now report the field absent.

```
$ kubectl get jobs -n nagar-platform -o json | … ttl per job
  bucket-init              ttl=ABSENT
  nagar-db-migrate         ttl=ABSENT
  nagar-kafka-topics       ttl=ABSENT
  nagar-ollama-models      ttl=ABSENT
  nagar-schema-index       ttl=ABSENT
  ---> jobs still carrying a TTL: 0
$ kubectl get applications -n nagar-system --no-headers | awk '{print $2"/"$3}' | sort | uniq -c
     16 Synced/Healthy
```

`OutOfSync` is a drift signal again rather than a timer artefact, and the heavy init work stops
repeating. Shipped the sanctioned way: `b6bab49` (fix + ADR-032 + §12.37) → mirror `phase13-5`
(`sha256:3e7ccca8…`, payload at a byte-identical HEAD) → transport advanced server-side → Argo.
The three orphaned pods from the old cycles are left in place as the evidence trail; §12.37
explains how to read them.

### G13.10 `Replace=true` was never the trigger: 0 syncs in 76 minutes at an unchanged revision

G13.9 removed one of the two things that could make an init Job re-run itself. The other was left
explicitly open in ADR-032: all five Jobs also carry
`argocd.argoproj.io/sync-options: Force=true,Replace=true`, and whether *that* re-runs a Job whose
spec has not changed was never separated from the TTL evidence. The Phase-4 record had blamed
`Replace=true` for the churn, so the honest state was "unknown", not "fixed".

Reasoning alone cannot settle it, for the same reason the TTL loop survived two phases of review: a
snapshot shows `Synced`, and the loop only exists *between* snapshots. So it was settled by
watching. Live state was sampled every 20 s (every 60 s after the first 20 minutes) at the synced
revision `b6bab49`, recording per Job the identity fields (`uid`, `creationTimestamp`,
`resourceVersion`, `completionTime`), the pod name and start time, and per Application
`sync.status`, `health.status`, `reconciledAt` and `operationState.finishedAt`.

```
window 2026-10-06T06:23:13Z .. 07:39:43Z   5 Jobs, 136 samples, 20 s then 60 s
  135 of 135 samples per Application: Synced/Healthy
  bucket-init          STABLE   uid=1 created=1 rv=1 podRuns=1
  nagar-db-migrate     STABLE   uid=1 created=1 rv=1 podRuns=1
  nagar-kafka-topics   STABLE   uid=1 created=1 rv=1 podRuns=1
  nagar-ollama-models  STABLE   uid=1 created=1 rv=1 podRuns=1
  nagar-schema-index   STABLE   uid=1 created=1 rv=1 podRuns=1
  ---> job recreations: 0     non-Synced app samples: 0
```

A recreate changes `uid` *and* `creationTimestamp`; a re-run starts a new pod. Neither happened to
any of the five, and no Application left `Synced`/`Healthy` for the whole window — so
`nagar-phase6-vector-llm`, the app that was flapping on the TTL, did not flap once.

The controller log says why, and it is mechanical rather than lucky:

```
$ kubectl -n nagar-system logs statefulset/argocd-application-controller --since=180m | …
nagar-phase3-object-cache  last sync op = 05:29:53Z
    after it: comparisons=43  auto-sync-declined(Synced)=43  sync-ops-started=0
              status-transitions=0   log reaches 07:36:56Z
nagar-phase4-messaging     last sync op = 05:29:53Z
    after it: comparisons=40  auto-sync-declined(Synced)=41  sync-ops-started=0
              status-transitions=0   log reaches 07:34:23Z
nagar-phase5-postgres      last sync op = 05:29:55Z
    after it: comparisons=42  auto-sync-declined(Synced)=42  sync-ops-started=0
              status-transitions=0   log reaches 07:34:19Z
nagar-phase6-vector-llm    last sync op = 05:34:53Z
    after it: comparisons=41  auto-sync-declined(Synced)=41  sync-ops-started=0
              status-transitions=0   log reaches 07:36:53Z
```

`Replace` is a **sync option**: it selects *how* Argo writes a resource it has already decided to
sync, so it is read only inside a sync operation. Every one of those reconciliations logged
`Skipping auto-sync: application status is Synced` with `sync_ms: 0` and `auto_sync_ms: 0` — the
auto-sync path was entered, found nothing to do and declined. Not one `Syncing`, `Initialized new
operation` or `Updated sync status: OutOfSync -> Synced` appears after the last legitimate sync, so
the option was never read. The same stream holds the *before* case for comparison: at 05:14:42
`nagar-phase6-vector-llm` went `Synced -> OutOfSync`, `Initiated automated sync to '5129ea37…'`,
`Syncing` — the TTL re-run, live. One log, one app, both behaviours, and the difference is a field
that no longer exists.

The clock was also carried past the exact instants at which the deleted TTLs used to fire, which is
the stronger claim: the controller was not merely idle, it was idle *at the moment it previously
acted*. Three of the five Jobs' former periods genuinely elapsed inside the window —

```
  Job                  created      former TTL   former expiry   crossed   sample after
  nagar-db-migrate     05:29:55Z    3600 s       06:29:55Z       yes       06:30:00Z+
  nagar-ollama-models  05:29:53Z    7200 s       07:29:53Z       yes       07:30:39Z
  nagar-schema-index   05:34:53Z    7200 s       07:34:53Z       yes       07:35:41Z
  bucket-init          05:29:53Z    86400 s      2026-10-07T05:29:53Z   no  — unreachable here
  nagar-kafka-topics   05:29:53Z    86400 s      2026-10-07T05:29:53Z   no  — unreachable here
```

— and samples either side of each instant show the same `uid`, the same `creationTimestamp` and
the same single `Succeeded` pod. For `bucket-init` and `nagar-kafka-topics` the argument stays
arithmetical, because their 86400 s periods are a day long and no window can be held open that
long: the field is absent, so the TTL controller has nothing to act on.

**Outcome: no manifest change was required.** `Replace=true` does not re-run an unchanged Job, so
there was nothing to remove and no transport advance to make. ADR-032's "Still open" bullet is
replaced with the closed finding plus this boundary evidence, and the live surface was re-read a
final time after the last boundary: five Jobs, five unchanged `uid`s, `ttl=ABSENT` on all five, and
16/16 Applications `Synced/Healthy`.

Limitations, stated rather than implied: the 24 h periods were not observed to elapse; the window
confirms the option is inert when the spec is unchanged, and says nothing about whether a *changed*
spec should re-run the Job — it should, and still does. What it does settle is that periodic
re-indexing is not a side effect of how these Jobs are synced.
