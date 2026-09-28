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
