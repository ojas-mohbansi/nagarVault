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
map to `agentic/phase-c-tagmap.txt` (103 rows: 21 `KEEP-PIN`, 82 `DELETE`) with the
machine plan in `agentic/phase-c-plan.json` (pin set, keep set, per-tag digests,
delete plan, anomalies). Sanity gates before any deletion: the 21 pinned repo:tag
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
