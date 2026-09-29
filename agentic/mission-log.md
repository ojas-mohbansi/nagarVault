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
