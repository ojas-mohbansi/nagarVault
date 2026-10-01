# Substrate lifecycle — rebuild, reseal, hygiene

How-to recipes for the disposable k3d substrate that runs NagarVault on a workstation:
back up live state, reclaim Docker space, rebuild the cluster with named volumes,
restore the platform from git, reseal cluster secrets, and keep the host clean
week over week.

**Audience:** the operator or agent who maintains this repo. Assumed: working
`kubectl`/`docker`/`k3d`/`kustomize`/`kubeseal` muscle memory and familiarity with the
invariants in [AGENTS.md](../AGENTS.md). The evidence narrative behind every command
here lives in [agentic/mission-log.md](../agentic/mission-log.md) — this page is the
recipe, not the story.

**Run everything from the repo root.** Every command below was executed and verified on
this substrate; where a step once failed, the failure mode is named inline.

---

## 0. Prerequisites and standing gates

Kubeconfig, in the proven form (MSYS silently rewrites a `$TEMP`-based `--kubeconfig`
argument because this bash exports `TEMP=/tmp` — use the env var with an explicit
Windows path; see [§7](#7-windowsmsys-trap-table)):

```bash
k3d kubeconfig get nagar | sed 's/host.docker.internal/127.0.0.1/g' > "$TEMP/kubeconfig"
export KUBECONFIG='C:/Users/styli/AppData/Local/Temp/kubeconfig'
```

30-second health check before and after every recipe:

```bash
kubectl get nodes --no-headers                                   # expect Ready
kubectl -n nagar-system get applications.argoproj.io \
  -o custom-columns=S:.status.sync.status,H:.status.health.status --no-headers \
  | sort | uniq -c                                               # expect 15 Synced Healthy
curl -s --noproxy '*' http://localhost:35000/v2/_catalog         # expect 24 repositories
```

Standing gates that apply to every section:

- **I-1** — the cluster reconciles from git. Out-of-band work below is limited to the
  documented exceptions (bootstrap applies, pod deletes of Deployment-owned pods,
  `k3d` lifecycle) and is recorded in the mission log.
- **I-3** — secret values live only in shell variables or files outside git, and are
  shredded after use. Never displayed.
- **I-9** — repo changes stay inside the declared subtree for the task.
- **Evidence-first** — before any destructive step, write the full inventory/map to a
  file and commit it. The mirror cycle's `kubectl apply` is always gated on its
  `kustomize build` succeeding.
- All manifest applies use `kubectl apply --server-side --force-conflicts` over a
  `kustomize build --load-restrictor LoadRestrictionsNone` output.

---

## 1. How to back up live state before a destructive change

### 1.1 Dump `nagardb`

Postgres here is a plain StatefulSet (no CNPG CRD): `postgres-1` primary,
`postgres-2` replica. Detect the primary, dump over TCP (the container socket enforces
peer auth), prove the dump:

```bash
PGPASS=$(kubectl -n nagar-platform get secret nagar-postgres-bootstrap \
  -o jsonpath='{.data.password}' | base64 -d)
for p in postgres-1 postgres-2; do
  kubectl -n nagar-platform exec "$p" -c postgres -- sh -c \
    "PGPASSWORD='$PGPASS' psql -h 127.0.0.1 -U nagar -d nagardb -tAc 'SELECT pg_is_in_recovery()'"
done                       # primary prints f; dump from that pod
kubectl -n nagar-platform exec postgres-1 -c postgres -- sh -c \
  "PGPASSWORD='$PGPASS' pg_dump -h 127.0.0.1 -U nagar -d nagardb --no-owner --no-privileges" \
  > nagardb.sql
grep -c 'CREATE TABLE' nagardb.sql   # gate: expect 8 (users, sessions, audit_logs, 5 dept tables)
grep -c '^COPY ' nagardb.sql         # gate: expect 8 data sections
```

Roles (`nmc_officer`, `health_officer`) are phase-5 DDL objects and come back with the
schema on restore — do not dump them separately.

### 1.2 Mirror the `raw-media` bucket

Use the sanctioned fixture pod (kept under
`deploy/phases/08-edge/e2e/fixtures/nagar-minio-backup-pod.yaml`): it mirrors the
bucket with `mc`, tars it, writes a `SHA256SUMS`, prints `BACKUP-READY`, and sleeps for
the copy-out. Credentials stay in-pod via `secretKeyRef` — note `envFrom` injects
secret keys **verbatim** (`accessKey`), so the fixture maps them to the names the
script expects explicitly.

```bash
kubectl apply -f deploy/phases/08-edge/e2e/fixtures/nagar-minio-backup-pod.yaml
kubectl -n nagar-platform wait \
  --for=jsonpath='{.status.containerStatuses[0].state.running.startedAt}' \
  pod/nagar-minio-backup --timeout=120s
kubectl -n nagar-platform logs nagar-minio-backup | grep BACKUP-READY   # gate
```

Copy the archive out (Git-Bash): `kubectl cp` misclassifies both path styles here, so
stream over `exec` with the MSYS guard, then verify the hash **before** deleting the
pod:

```bash
MSYS_NO_PATHCONV=1 kubectl -n nagar-platform exec nagar-minio-backup -c backup -- \
  sh -c 'base64 /backup/raw-media-backup.tar.gz' > raw-media.b64
base64 -d raw-media.b64 > raw-media-backup.tar.gz
sha256sum raw-media-backup.tar.gz        # must equal the pod's SHA256SUMS line
kubectl -n nagar-platform delete pod nagar-minio-backup
```

### 1.3 Record it

Keep both artifacts plus the recorded sizes/hashes in a dated host directory outside
git (e.g. `C:\Users\styli\.k3d\nagar-backup-<date>\`). Qdrant collections and Ollama
models are intentionally **not** backed up: their Jobs rebuild them idempotently from
git (see [§4.3](#43-wait-for-convergence-and-job-end-states)).

---

## 2. How to reclaim Docker space without a rebuild

### 2.1 Host-level prune (safe anytime)

```bash
docker system df                      # record before
docker builder prune -af              # build cache (was 25.7 GB here)
docker image prune -f                 # dangling images only
docker container prune -f             # exited containers only
docker system df                      # record after; volumes must be byte-identical
```

**Never** `docker volume prune` or `docker system prune --volumes`: all mission state
lives in volumes.

### 2.2 Registry tag-prune + garbage-collect

The keep set is mechanical and has **two** sources:

1. **every `digest:` value under `deploy/phases/*/digest-pins/kustomization.yaml`**,
   whatever entry shape carries it (structure-independent regex — phase-1 files use
   bare `name:`+`digest:`);
2. **the mirror transport tag** resolved to its digest — the gitops tree references
   `mission/git-repo-mirror` by `newTag:` in
   `deploy/phases/02-gitops/git-mirror/kustomization.yaml`, **not** by digest, so
   digest pins alone do NOT protect the tag the cluster's git sync depends on.
   **Deleting the current mirror tag silently breaks every Application's sync.**

1. Freeze writes and mount a one-shot GC registry on the payload volume:

   ```bash
   docker stop k3d-nagar.localhost
   docker run -d --name nagar-registry-gc -p 127.0.0.1:35100:5000 \
     -v nagar-registry-data:/var/lib/registry \
     -e REGISTRY_STORAGE_DELETE_ENABLED=true registry:2
   ```

2. Write the full tag→digest map to a file **first** (evidence-first), with the
   multi-media-type Accept header or HEADs return nothing for index images:

   ```bash
   ACCT='application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json'
   grep -rhoE 'digest:\s*sha256:[0-9a-f]{64}' deploy/phases/*/digest-pins/kustomization.yaml \
     | awk '{print $2}' | sort -u > keep-digests.txt
   : > registry-map.txt
   for r in $(curl -s --noproxy '*' http://127.0.0.1:35100/v2/_catalog | python -c "import json,sys;print(' '.join(json.load(sys.stdin)['repositories']))"); do
     for t in $(curl -s --noproxy '*' "http://127.0.0.1:35100/v2/$r/tags/list" | python -c "import json,sys;print(' '.join(json.load(sys.stdin).get('tags') or []))"); do
       d=$(curl -sI --noproxy '*' -H "Accept: $ACCT" "http://127.0.0.1:35100/v2/$r/manifests/$t" \
           | tr -d '\r' | awk 'tolower($1)=="docker-content-digest:"{print $2}')
       echo "$r:$t $d" >> registry-map.txt
     done
   done
   # source 2: the mirror transport tag (newTag-referenced, NOT digest-pinned)
   MIRROR_TAG=$(awk '/newTag:/{print $2}' deploy/phases/02-gitops/git-mirror/kustomization.yaml | head -1)
   echo "mirror tag: $MIRROR_TAG  (add its digest to the keep set)"
   curl -sI --noproxy '*' -H "Accept: $ACCT" \
     "http://127.0.0.1:35100/v2/mission/git-repo-mirror/manifests/$MIRROR_TAG" \
     | tr -d '\r' | awk 'tolower($1)=="docker-content-digest:"{print $2}' >> keep-digests.txt
   sort -u keep-digests.txt -o keep-digests.txt
   ```

3. Derive the delete list, **review it** (it must NOT contain the mirror transport
   tag from step 2's source 2), commit both files, then delete by digest
   (202 = accepted, 404 = already gone, anything else = stop):

   ```bash
   awk 'NR==FNR{keep[$1];next} $2 && !($2 in keep)' keep-digests.txt registry-map.txt > delete-list.txt
   wc -l delete-list.txt                # review before continuing
   while read -r ref dig; do
     curl -s --noproxy '*' -X DELETE -o /dev/null -w "%{http_code} $ref\n" \
       "http://127.0.0.1:35100/v2/${ref%:*}/manifests/$dig"
   done < delete-list.txt
   ```

4. Garbage-collect inside the one-shot, restore the live registry, prove continuity:

   ```bash
   docker exec nagar-registry-gc sh -c \
     'registry garbage-collect /etc/docker/registry/config.yml --dry-run'   # review
   docker exec nagar-registry-gc sh -c \
     'registry garbage-collect /etc/docker/registry/config.yml'
   docker rm -f nagar-registry-gc && docker start k3d-nagar.localhost
   curl -s --noproxy '*' http://localhost:35000/v2/_catalog   # catalog + pinned HEADs
   ```

**Expectation, from measurement:** freed bytes are small when the deleted tags shared
layers — after removing 82 of 103 tags here, the payload barely moved (~21.2 → 21.1 GB)
because the remaining bytes **are** the pinned working set. The real byte lever on a
bloated substrate is [§3](#3-how-to-rebuild-the-cluster-with-named-volumes), which
wipes the k3s containerd store (45 GB → 246 MB here).

---

## 3. How to rebuild the cluster with named volumes

Destructive by design: in-cluster data is lost (that is what [§1](#1-how-to-back-up-live-state-before-a-destructive-change)
is for) and the sealed-secret material changes ([§5](#5-how-to-reseal-cluster-secrets-one-time-per-cluster)).

### 3.1 Pre-create volumes and copy the registry payload

```bash
for v in k3d-nagar-server-0-k3s k3d-nagar-server-0-kubelet k3d-nagar-server-0-cni \
         k3d-nagar-server-0-logs nagar-registry-data; do docker volume create "$v"; done
```

Do **not** create a bind for `/k3d/images` — k3d owns that mount and auto-creates its
own `k3d-nagar-images` volume; an explicit bind fails cluster creation with
`Duplicate mount point: /k3d/images`.

Copy the payload behind a write fence, and prove the copy **as a registry** (A/B
against two temp instances) before anything is deleted:

```bash
docker stop k3d-nagar.localhost
REGVOL=$(docker inspect k3d-nagar.localhost \
  --format '{{range .Mounts}}{{if eq .Destination "/var/lib/registry"}}{{.Name}}{{end}}{{end}}')
echo "registry payload volume: $REGVOL"   # confirm before copying
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$REGVOL":/from:ro -v nagar-registry-data:/to registry:2 \
  sh -c 'cp -a /from/. /to/ && du -sb /from /to && find /from /to -type f | wc -l'
# A/B proof: temp registries on :35100 (old) and :35101 (copy) — catalogs equal,
# tag sets equal, every pinned digest HEAD-equal on both. Reuse the §2.2 enumeration.
```

(The `MSYS_NO_PATHCONV=1` guard is required for the in-container `sh -c` string too.)

### 3.2 Delete, then verify what k3d removed

```bash
k3d cluster delete nagar
k3d registry delete nagar.localhost
docker ps -a --format '{{.Names}}' | grep -c k3d    # expect 0
```

k3d removes its **own anonymous volumes** with the cluster (verify each old hex ID is
gone with `docker volume inspect <id>`); your named volumes survive. If cluster
creation later fails with "No nodes found", look for a stale `k3d-nagar` **network**
kept alive by the registry container: `docker network disconnect k3d-nagar
k3d-nagar.localhost && docker network rm k3d-nagar`.

### 3.3 Recreate registry and cluster

```bash
k3d registry create nagar.localhost --port 35000 -v nagar-registry-data:/var/lib/registry
k3d cluster create nagar --servers 1 --image rancher/k3s:v1.31.5-k3s1 \
  --registry-use nagar.localhost:35000 \
  --volume 'C:/Users/styli/.k3d/nagar-storage:/var/lib/rancher/k3s/storage@server:*' \
  --k3s-arg "--disable=traefik@server:0" \
  --volume 'k3d-nagar-server-0-k3s:/var/lib/rancher/k3s@server:0' \
  --volume 'k3d-nagar-server-0-kubelet:/var/lib/kubelet@server:0' \
  --volume 'k3d-nagar-server-0-cni:/var/lib/cni@server:0' \
  --volume 'k3d-nagar-server-0-logs:/var/log@server:0'
k3d kubeconfig get nagar | grep 'server:'    # record the NEW API port
```

(Windows path form for the storage bind — an MSYS `/c/...` form once failed the
cluster's storage mount. Diagnose creation failures from the **full** log, never a
`tail`: the real error hid behind rollback lines twice.)

### 3.4 Continuity gates, then old-volume cleanup

Gate the cleanup on all of these passing: node Ready
(`kubectl wait --for=condition=Ready node/k3d-nagar-server-0 --timeout=240s`), catalog
200 with the expected repo count, every pinned digest HEAD-equal to its git pin
([§2.2](#22-registry-tag-prune--garbage-collect) enumeration against
`localhost:35000`). Only then remove leftover old volumes **by ID** — never a blind
`docker volume prune`. Record `docker system df` and the final volume list.

---

## 4. How to restore the platform from git after a rebuild

### 4.1 Bootstrap order

On a virgin cluster, `02-gitops` cannot land first — there are no namespaces. Build
and apply the phase-1 substrate tree, wait for CRDs to establish, re-apply (the first
pass bounces CRD-dependent objects; the re-apply is idempotent by design), then apply
the gitops tree:

```bash
kustomize build --load-restrictor LoadRestrictionsNone deploy/phases/01-substrate > /tmp/p1.yaml
kubectl apply --server-side --force-conflicts -f /tmp/p1.yaml
kubectl wait --for=condition=Established crd --all --timeout=180s
kubectl apply --server-side --force-conflicts -f /tmp/p1.yaml
kustomize build --load-restrictor LoadRestrictionsNone deploy/phases/02-gitops > /tmp/p2.yaml
kubectl apply --server-side --force-conflicts -f /tmp/p2.yaml
```

The 15 Applications sync from the in-cluster git mirror (`git://git-repo-mirror…`),
which serves the tag recorded in `deploy/phases/02-gitops/git-mirror/kustomization.yaml`
— advance it through the mirror cycle (clone bare → build gated → push → apply) when
the sealed secrets change ([§5](#5-how-to-reseal-cluster-secrets-one-time-per-cluster)).

### 4.2 Land the sealed secrets

Applications will sync the pre-reseal revision first and secret-consuming pods will sit
in `CreateContainerConfigError` — correct fail-closed behavior. Land the resealed
blobs ([§5](#5-how-to-reseal-cluster-secrets-one-time-per-cluster)); the
`nagar-platform` pair arrives via Argo inside its phase trees, the `nagar-app` trio via
the bootstrap ritual `kubectl apply -f deploy/phases/01-substrate/secrets/` (that
directory is deliberately referenced by no kustomization). Kubernetes/Argo then
self-heals the starved pods.

### 4.3 Wait for convergence and job end-states

All five idempotent Jobs must reach their end state: `bucket-init`,
`nagar-kafka-topics`, `nagar-db-migrate`, `nagar-ollama-models` → `Complete`;
`nagar-schema-index` → `Complete` with `INDEX-SYNC-OK` in its log. The schema-index
Job has no dependency wait: on a cold boot it can exhaust its backoff before
Qdrant/Ollama are ready (evidence: `BackoffLimitExceeded` in Job conditions). The
sanctioned re-run is `kubectl -n nagar-platform delete job nagar-schema-index` — Argo
recreates it, and it completes once dependencies are up.

### 4.4 Reseed the admin and prove the edge

The first admin cannot be created through `POST /create` (it requires an admin JWT);
seed it out-of-band per [OPERATIONS §5](OPERATIONS.md#5-first-admin-user-bootstrap-ritual):

```bash
PW=$(openssl rand -hex 14)   # never displayed, never written to git
kubectl -n nagar-app exec deploy/auth-service -- \
  python seed_admin.py --username admin8 --user-id admin8-001 --password "$PW" >/dev/null
```

Re-running is a no-op if the user exists. Prove the stack end to end (inline
port-forward, status-only output, cookie jar shredded after):

```bash
kubectl -n nagar-system port-forward --address 127.0.0.1 svc/traefik-edge 8449:443 &
sleep 3
curl -sk --ssl-no-revoke --resolve k3d.nagar.internal:8449:127.0.0.1 \
  -H 'Content-Type: application/json' -d "{\"username\":\"admin8\",\"password\":\"$PW\"}" \
  -o /dev/null -w '%{http_code}\n' https://k3d.nagar.internal:8449/auth/login   # expect 200
kill %1
```

---

## 5. How to reseal cluster secrets (one-time per cluster)

**Why:** the Sealed Secrets controller generates its keypair at first start; on this
disposable substrate the private-key backup is ephemeral by design (the G1.2 drill
shreds it after verification). After any rebuild the old sealed blobs are
mathematically dead — reseal per [OPERATIONS §4](OPERATIONS.md#4-bootstrap-secrets-one-time-per-cluster).

The five identities (name / namespace / data keys / type):

| Secret | Namespace | Keys | Type |
|---|---|---|---|
| `nagar-jwt` | nagar-app | `jwtSecret` | Opaque |
| `nagar-minio` | nagar-app | `accessKey`, `secretKey` | Opaque |
| `nagar-postgres-app` | nagar-app | `databaseUrl` | Opaque |
| `nagar-minio-server` | nagar-platform | `accessKey`, `mcHostLocal`, `secretKey` | Opaque |
| `nagar-postgres-bootstrap` | nagar-platform | `username`, `password` | kubernetes.io/basic-auth |

Coupling rules that must survive the reseal:

- **ADR-011 ¶5** — the `nagar` role password is pinned, not generated per component:
  the same value goes into `nagar-postgres-app.databaseUrl` **and**
  `nagar-postgres-bootstrap.password` in the same change.
- MinIO keys are shared across `nagar-minio` and `nagar-minio-server`;
  `mcHostLocal` is the `MC_HOST_local` URL form:
  `http://<access>:<secret>@minio.nagar-platform.svc.cluster.local:9000`.
- `databaseUrl` format: `postgresql://nagar:<password>@postgres-rw.nagar-platform.svc.cluster.local:5432/nagardb`.

Procedure:

1. Generate all fresh values as shell variables; stage plaintext Secret manifests in a
   temp dir (values only ever base64/`stringData` inside those files).
2. Export the **new** controller cert — the secret name is generated
   (`kubectl -n nagar-system get secrets | grep sealed-secrets-key`), do not guess it:
   `kubectl -n nagar-system get secret <name> -o jsonpath='{.data.tls\.crt}' | base64 -d > ss-cert.crt`.
3. Seal each with the pinned tool: `kubeseal --format yaml --cert ss-cert.crt < plain.yaml > sealed.yaml`.
4. Compare `encryptedData` key sets against the old committed files — identical key
   names, new ciphertexts only.
5. Commit the five files (subtrees: `01-substrate/secrets/`, `03-object-cache/secrets/`,
   `05-postgres/secrets/`) plus the mirror tag bump; ship via the mirror cycle
   (build gated, then apply); shred the plaintext dir.
6. Land per [§4.2](#42-land-the-sealed-secrets) and verify via the controller log
   (`Unsealed successfully` per secret) and `kubectl get secrets` in both namespaces.

---

## 6. How to run and schedule weekly hygiene

`agentic/ops/docker-hygiene.ps1` prunes three things and nothing else: build cache
older than 7 days, dangling images, and exited **non-k3d** containers. It structurally
cannot touch volumes (all mission state) and keeps any container whose name is
`k3d`-prefixed even when exited.

```powershell
# run now (writes %TEMP%\docker-hygiene.log before/after docker system df)
powershell -NoProfile -ExecutionPolicy Bypass -File agentic\ops\docker-hygiene.ps1

# registered task: 'NagarVault Docker Hygiene', Sundays 03:00, StartWhenAvailable
powershell -Command "Start-ScheduledTask -TaskName 'NagarVault Docker Hygiene'; Start-Sleep 12; Get-ScheduledTaskInfo -TaskName 'NagarVault Docker Hygiene' | Select LastRunTime, LastTaskResult"
```

Two verified safety behaviors — do not regress them when editing:

1. **k3d guard is prefix-based.** `docker inspect` names carry a leading slash; strip
   it and match `k3d*`. A substring `*k3d*` match falsely protects any container with
   "k3d" anywhere in its name (proven with a `nonk3d` decoy).
2. **The engine gate tests `$LASTEXITCODE`, not output.** Under a dead endpoint,
   `docker.exe` still prints its error banner on stdout in Windows PowerShell 5.1, so
   an output-presence test never detects a down engine (proven; the abort path must
   log `engine down; aborting this run (nothing pruned)` and exit before any prune).

---

## 7. Windows/MSYS trap table

One line each; all session-proven on this substrate. The platform-level
troubleshooting matrix lives separately in
[OPERATIONS §12](OPERATIONS.md#12-troubleshooting-matrix-symptom--cause--fix) —
these are the Windows/MSYS/registry traps it does not cover.

| Trap | Rule |
|---|---|
| MSYS rewrites argument-position POSIX paths (in-pod paths, `docker run … sh -c`) | Prefix `MSYS_NO_PATHCONV=1`; keep in-pod paths inside whole-string `sh -c` |
| …but with that guard, a `$TEMP`-based `--kubeconfig` argument dies (`TEMP=/tmp` here) | Use `KUBECONFIG='C:/...'` env form; never combine both |
| `kubectl cp` unusable Git-Bash→host (both path styles misclassified) | `exec … -- sh -c 'base64 <file>'` → `base64 -d` |
| Python-spawned `curl` stalls through the Windows proxy | Always `curl --noproxy '*'` from scripts |
| Registry API returns nothing for index images | Send the 4-media-type `Accept` header on every HEAD/GET |
| `docker inspect` names carry a leading slash; k3d containers are `k3d`-prefixed | Strip slash, prefix-match guards |
| `docker.exe` under a dead endpoint prints a 52-line banner on stdout (PS 5.1) | Gate on `$LASTEXITCODE`, never on output presence |
| One-shot `registry:2` runs auto-create anonymous volumes | Clean up by ID; never blind `volume prune` |
| `kubeseal` cannot read a cert extracted from a guessed secret name | List `sealed-secrets-key*` secrets first |
| `diskpart` left attached after a killed script ⇒ Docker `ERROR_SHARING_VIOLATION` masquerading as disk-identity errors | Detach before any re-attach; read full logs, not tails |
| curl against the air-gapped CA fails schannel revocation | Add `--ssl-no-revoke` |
| `envFrom` injects secret keys verbatim (`accessKey`, not `MINIO_ACCESS_KEY`) | Map with explicit `secretKeyRef` envs |
