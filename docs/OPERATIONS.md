# Operations — NagarVault

> Runbooks. Hub: [AGENTS.md](../AGENTS.md). If a procedure is missing here, write it here — do not
> improvise one-off fixes (AGENTS.md §6.4).

## 1. Prerequisites (target state, Phase 1+)

- One or more Linux nodes (same room, same L2 network), 16 GB RAM minimum (32 GB recommended for
  the SLM tier), 100 GB+ SSD for data plane.
- Build host (any OS) with `docker`, `kustomize`, `kubeseal`, `cosign`, `syft`, `trivy`, `kubectl`.
- Internal registry reachable at `registry.nagar.internal:5000` from all nodes.
- k3s binaries and all images staged air-gapped (§2.3).

## 2. Cluster bootstrap (Phase 1)

### 2.1 Install k3s (online host)
```bash
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644
sudo kubectl get nodes   # node Ready within ~30s
```

### 2.2 Install k3s (air-gapped)
Follow k3s air-gap docs: download `k3s` binary + images tarball on the build host, stage on the node,
install with `INSTALL_K3S_SKIP_DOWNLOAD=true`. Bundled Traefik and local-path provisioner make this
a zero-dependency install.

### 2.3 Stage images into the internal registry
```bash
# On the build host — for every pinned image digest referenced by the manifests:
docker pull <image>@<digest>
docker tag  <image>@<digest> registry.nagar.internal:5000/<image>:<tag>
docker push registry.nagar.internal:5000/<image>:<tag>
```
Cluster pulls reference only `registry.nagar.internal:5000` (AGENTS.md I-11).

## 3. Deploy the platform (normal path)

Deployment is **git push**, nothing else (AGENTS.md I-1):

```bash
git checkout phase/NN-... && git push          # open PR, merge
argocd app sync nagar-bootstrap                # or wait for auto-sync (Phase 2+)
argocd app get nagar-bootstrap                 # expect: Healthy / Synced
```

App-of-apps (`deploy/phases/02-gitops/app-of-apps.yaml`, Phase 2) owns child Applications; you
never `kubectl apply` by hand. Rollback = `git revert` + sync (PHASES.md §3).

## 4. Bootstrap secrets (one-time per cluster)

```bash
# 1. Create plaintext files OUTSIDE git
export JWT_SECRET=$(openssl rand -hex 32)
# ... postgres password, minio keys — SECURITY.md §6.2 key map

# 2. Seal with the cluster's Sealed Secrets public cert
kubeseal --format yaml < jwt-secret.yaml > deploy/phases/01-substrate/secrets/nagar-jwt.yaml
rm -P jwt-secret.yaml                     # shred plaintext
git add deploy/.../nagar-jwt.yaml && git commit
```

Backup the Sealed Secrets controller key FIRST (§7). Without it, sealed secrets are unrecoverable.

## 5. First admin user (bootstrap ritual)

`/create` requires an admin JWT, so the first admin is seeded out-of-band (unchanged from today):

```bash
kubectl -n nagar-app exec deploy/auth-service -- \
  python seed_admin.py --username admin --user-id admin-001
# The script generates and prints a strong password once; record it in the operator vault.
```

Then log in at the edge and create additional users via the admin-authenticated `POST /create`.
Re-running the seed is safe (no-op if user exists).

## 6. Model provisioning (zero-touch)

Ollama models are provisioned by the checksum-pinned Job (exemplar
`docs/manifests/exemplars/ollama-model-job.yaml`), which runs on every sync where the model spec
changes and is a no-op otherwise. No manual `ollama pull`, ever. Verify:

```bash
kubectl -n nagar-platform exec deploy/ollama -- ollama list
# expect: bge-m3 and qwen3:1.7b present
```

## 7. Backups & disaster recovery

| Asset | Mechanism | Schedule |
|---|---|---|
| PostgreSQL | CNPG scheduled base + WAL backups → MinIO bucket `pg-backups` | base daily, WAL 5 min |
| Kafka | topic data is reconstructable from source systems; DLQ is inspectable | n/a (accepted risk, ADR-006) |
| MinIO media | object storage is the primary copy | n/a |
| Qdrant `nagar_schema` | rebuildable by re-running schemaIndexer (idempotent) | n/a |
| Redis | ephemeral by design (TTL intents) | n/a |
| Sealed Secrets keys | operator-stored offline copy | on creation + every rotation |

**Sealed Secrets key backup (do this first, not last):**
```bash
kubectl -n nagar-system get secret -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o yaml > sealed-secrets-master-key.yaml   # store offline, encrypted
```

### Restore drill (quarterly, evidence recorded — Phase 5)

The drill is a version-controlled tree that Argo deliberately does not reconcile, applied and
deleted as a unit (ADR-020, sanctioned as §9.5). It is a **data** drill, not a "a pod started"
drill: it writes a canary row into the source, takes a fresh base backup, restores that backup into
a scratch cluster, and then connects **as the application role with the application's sealed
password** to assert the schema, the canary, and that the grant matrix survived the round trip.

```bash
BUILD="kustomize build --load-restrictor LoadRestrictionsNone deploy/phases/05-postgres/restore-drill"

# 1. apply the drill (canary Job runs first and writes into the SOURCE warehouse; idempotent)
$BUILD | kubectl apply -f -
kubectl -n nagar-platform wait --for=condition=complete job/pg-drill-canary --timeout=10m

# 2. take a base backup that contains the canary
kubectl -n nagar-platform wait --for=jsonpath='{.status.phase}'=completed backup/pg-drill-backup --timeout=20m

# 3. recover the scratch cluster from the object store (latest base backup + WAL replay)
kubectl -n nagar-platform get backup pg-drill-backup -o jsonpath='{.status.phase}{"\n"}'
kubectl -n nagar-platform wait --for=condition=Ready cluster/postgres-restore-drill --timeout=20m

# 4. verify — schema, canary, and the SECURITY §3.3 grant matrix, as the application role
kubectl -n nagar-platform wait --for=condition=complete job/pg-drill-verify --timeout=10m
kubectl -n nagar-platform logs job/pg-drill-verify          # expect the final line: RESTORE-DRILL-VERIFIED

# 5. tear the drill down (nothing here is Argo-owned, so nothing prunes it for you)
$BUILD | kubectl delete -f -
```

Record the verify Job's output with the drill date. Expect ~3–6 minutes end to end on the
reference substrate. A `DRILL-FAILED` line in step 4 means the backup chain is broken — that is an
incident to fix, not a drill to re-run until it passes. The canary row stays in
`nmc_complaints` (`source_record_id = 'p5-drill-canary-001'`) as the audit trail; delete it only if
the warehouse is being reset.

## 8. Common operations

| Task | Command |
|---|---|
| Re-index schema vectors | `curl -X POST http://schema-indexer:4005/reindex` or admin `POST /vector/resync` |
| Inspect DLQ | admin UI/`GET /dlq` (adminService :4001) |
| View recent audit | `GET /audit-logs` (adminService) |
| Restart one service | `kubectl -n nagar-app rollout restart deploy/<name>` (allowed: reads intent from git unchanged) |
| Rotate JWT secret | SECURITY.md §6.4 procedure |
| Force model re-provision | delete the completed model Job; Argo recreates it |

## 9. Sanctioned imperative exceptions (I-1)

The only permitted out-of-band `kubectl` mutations, all documented here:
1. `seed_admin.py` execution in §5 (bootstrap identity).
2. Emergency secret rotation while a git fix is prepared (must be followed by a git commit that
   reconciles state within one business day).
3. Deleting a stuck Job/PVC under Argo's ownership to unblock reconciliation (then let Argo recreate).
4. Advancing the git transport (ADR-018): once per mirror cycle, after pushing the new mirror image,
   apply the mirror subtree with the exact command in §12.16. This is the "push to the git remote"
   step, not a workload edit — the cluster has no way to learn about a new mirror tag otherwise.
   Apply the same git tree Argo reads; never hand-edit the live Deployment.
5. Applying and then deleting the restore drill (§7, ADR-020): the drill tree is intentionally
   outside the reconciled tree because a permanently running scratch cluster would spend the
   resource budget the platform needs and would still restore only once. Both halves of the
   procedure are mandatory — an applied-and-forgotten drill is the one way this exception turns
   into drift, and it is visible as a second `Cluster` in `kubectl get cluster -n nagar-platform`.

Everything else: change git, let Argo converge.

## 10. Alerts → runbooks (Phase 9)

Every alert rule must carry a `runbook_url` annotation pointing to an anchor in this file. Initial
set: `KafkaConsumerLag` (→ §12.2), `CNPGBackupFailed` (→ §7), `PodCrashLooping` (→ §12.1),
`CertExpiringSoon` (→ §12.4), `Ingest5xxRate` (→ §12.3).

## 11. Post-deploy smoke test (E2E, scripted in Phase 10)

```bash
# 1. auth
curl -sf https://<edge>/auth/ | grep ok
# 2. login (seeded admin) — expect Set-Cookie session_token
curl -si -X POST https://<edge>/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","user_id":"admin-001","password":"<from vault>"}' | head -1
# 3. ingest a JSON-only event (expect 202 + eventId)
# 4. enrich lands in Postgres: SELECT COUNT(*) FROM nmc_complaints; (expect +1)
# 5. ask: POST /ask via edge (expect sql + data)
# 6. admin: GET /health/cluster (expect all up)
```

Phase 10 exit requires this script green on the Kubernetes stack.

## 12. Troubleshooting matrix (symptom → cause → fix)

| # | Symptom | Likely cause | Fix |
|---|---|---|---|
| 12.1 | Pod `CrashLoopBackOff` | bad env/secret, dependency unreachable | `kubectl logs`; check §6.2 key map; verify NetworkPolicy allows the flow (SECURITY §8) |
| 12.2 | enrichWorker lag / stale warehouse | Kafka consumer stuck, DLQ filling | check consumer group lag; inspect DLQ via admin; fix schema mismatch, replay topic |
| 12.3 | Ingestion 5xx | MinIO down, Redis down, Kafka down | `GET /health` names the down component; restart that StatefulSet only if Argo is synced (else fix git first) |
| 12.4 | TLS expired / cert errors | cert-manager issuance failure | check `Certificate` status + internal CA secret; renew via Argo sync after fixing issuer |
| 12.5 | `503 Ollama is unreachable` (slmService) | model Job not complete, Ollama PVC full | §6 verify; check PVC usage; NetworkPolicy slm→ollama open |
| 12.6 | `503 Schema index is empty` | schemaIndexer never ran / Qdrant empty | trigger `/reindex`; verify Qdrant collection `nagar_schema` count = 40 |
| 12.7 | Generated SQL always 403 | role mismatch, PII column hit, non-SELECT | check JWT role claim; adjust schema_docs wording; inspect `[ask] generated_sql` log |
| 12.8 | SQL generation very slow (CPU) | expected on CPU-only nodes | 10–30 s/query is normal; GPU node optional (node selector `accelerator: nvidia-gpu`) |
| 12.9 | `bge-m3` not found | model Job skipped/failed | §6; delete completed Job to force re-run |
| 12.10 | Argo `OutOfSync` forever | manual live mutation (I-1 violation) | `argocd app diff`, revert live change or commit it properly; never "fix" by disabling self-heal |
| 12.11 | Kyverno rejects a manifest | missing labels/probes/digest pin | fix the manifest to satisfy CONVENTIONS §5 and SECURITY §5; do not weaken policy |
| 12.12 | Upload PUT fails from browser | CORS/edge route misconfig | verify Traefik middleware origins match frontend origin (Phase 8 config) |
| 12.13 | A changed **Job** spec never lands: sync errors with `spec.template: Invalid value: … field is immutable`, then `Skipping auto-sync: already attempted sync …` for that revision | a Job pod template is immutable, so Argo cannot apply or diff the change; the failed revision is not retried until a new one arrives | declare `argocd.argoproj.io/sync-options: Force=true,Replace=true` on the Job (ADR-016). To un-wedge now: delete the Job (§9.3) and let Argo recreate it, then re-arm auto-sync with a new revision (mirror tag bump) |
| 12.14 | One StatefulSet is `OutOfSync` after every sync while its siblings are `Synced` | API-server defaults inside `spec.volumeClaimTemplates` (`apiVersion`, `kind`, `spec.volumeMode`) are not normalized by Argo's client-side differ; self-heal then runs *partial* syncs that consume the auto-sync attempt for each revision (it can starve a pending change elsewhere) | `kubectl diff --server-side --force-conflicts -f <sts>` (read-only) to isolate it; declare the defaulted fields in git (ADR-016). Never mask with `ignoreDifferences` |
| 12.15 | Strimzi operator logs `Exceeded timeout of 300000ms while waiting for Pods resource … to be ready` and **no such Pod exists**; `StrimziPodSet` reports `pods: 0` with a stale error condition | the pod-set controller reconciles on `StrimziPodSet` **change** events. If the last pod-create failed (e.g. an admission policy denied it) and the desired pod-set content has not changed since, nothing re-triggers it — the operator then waits out its 5-minute timeout for a pod nobody will create | fix the actual cause first (usually §12.11 — confirm with `kubectl apply --dry-run=server` on the pod extracted from the pod-set). Then delete the `StrimziPodSet`; the operator regenerates it from the `Kafka` CR in git and the pod is created (ADR-017 §6) |
| 12.16 | A change is committed and pushed to the mirror but Argo stays `Synced` on the **old** revision forever | the mirror advance is circular by design: Argo reads the new tag *from* the mirror pod, which is an Argo-managed Deployment, so it never learns a newer tag exists (ADR-018) | advance the transport once per cycle (§9.4): `kustomize build deploy/phases/02-gitops/git-mirror \| kubectl apply --server-side --force-conflicts -f -`, then `kubectl rollout status deploy/git-repo-mirror -n nagar-system`. Check the served revision with `kubectl get app -n nagar-system -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.sync.revision}{"\n"}{end}'` |
| 12.17 | A Service selects nothing / a NetworkPolicy matches nothing, yet both are `Synced` and look correct in git | the selector uses `app.kubernetes.io/*`, which an operator owns on the pods it creates: Strimzi overwrites `part-of`/`name`/`instance`/`managed-by` and **drops** `app.kubernetes.io/component` | select on the operator's own guaranteed labels instead (`strimzi.io/cluster` / `strimzi.io/kind` / `strimzi.io/name` / `strimzi.io/broker-role` for Strimzi — copy the selector from the operator's generated Service). Check with `kubectl get endpoints <svc>` rather than trusting the manifest (ADR-017 §3) |
| 12.18 | A vendored **CRD** is `OutOfSync` after every sync while its siblings from the same file are `Synced`; the sync itself reports success | the API server prunes empty `properties: {}` nodes (and similar no-op schema nodes) from an applied structural CRD schema, so the live object can never equal the upstream file. The differ sees the server's pruning as drift | localize with `argocd app diff <app>` — when the whole diff is a line or two, it is normalization, not drift. Declare the server-stored form: a JSON 6902 patch in the **consuming** phase that removes the pruned node, leaving `deploy/third_party/` pristine (ADR-002). Never `ignoreDifferences` a schema — that hides real drift. Precedent: `deploy/phases/04-messaging/strimzi/crd-schema-normalize-patch.yaml` |
| 12.19 | Broker is `Ready` and clients work, but the operator logs `Error getting broker config: java.util.concurrent.TimeoutException` every ~90 s and the `Kafka` CR never reaches `Ready` | Strimzi 1.x exposes more than the client listener: `PLAIN-29092`, `REPLICATION-9091` (used by the operator's AdminClient) and `CONTROLPLANE-9090` (KRaft quorum). A NetworkPolicy written only for the documented client port leaves the operator's own traffic denied (ADR-017 §5) | allow 9091 from the operator's namespace and 9090 only from broker pods. Confirm the diagnosis from the operator pod before touching manifests: `kubectl exec -n nagar-system deploy/strimzi-cluster-operator -- sh -c 'for p in 9090 9091 29092; do timeout 3 sh -c "cat < /dev/null > /dev/tcp/nagar-kafka-bootstrap.nagar-platform.svc/$p" 2>/dev/null && echo "OPEN $p" || echo "BLOCKED $p"; done'` |
| 12.20 | An Argo sync fails with `one or more synchronization tasks are not valid: namespace X is not permitted in project 'nagar'` and the retry counter climbs | the AppProject `spec.destinations` whitelist in `deploy/phases/02-gitops/root.yaml` does not contain the namespace a new resource targets — Application *destinations* are gated per resource, not per Application (Phase 5 hit this when the CNPG bundle introduced `cnpg-system`) | add the namespace to `root.yaml` and advance the transport. If the running sync does not pick the change up (its retries re-read the project, but a wedged revision may not), replay the phase-2 bootstrap tree once: `kustomize build deploy/phases/02-gitops \| kubectl apply --server-side --force-conflicts -f -` — the same byte-identity argument as §9.4. Then extend the app-of-apps (`apps/kustomization.yaml`) **in the same commit as the new Application file**: a file present but unregistered renders in `kustomize build` yet ships nothing |
| 12.21 | CloudNativePG denies the Cluster at admission: `spec.imageName: Invalid value …: Can't use just the image sha as we can't detect upgrades` | the operator parses the *tag* to detect major-version upgrades and refuses a bare-digest reference | keep the tag and the digest together: `<registry>/<image>:<tag>@sha256:<digest>`. The digest is still what kubelet resolves, so I-5 holds; the tag is frozen to the same immutable artifact |
| 12.22 | CloudNativePG denies the Cluster: `Memory request is lower than PostgreSQL shared_buffers value` | the operator validates the pod's memory request against `shared_buffers` (default 256MB+), which an air-gap minimal sizing easily undercuts | raise `resources.requests.memory` to at least `shared_buffers`, or lower `postgresql.parameters.shared_buffers` to match the request — the drill cluster does the latter so it can run at 192Mi |
| 12.23 | A cluster has zero pods and every ReplicaSet event says `admission webhook "validate.kyverno.svc-fail" denied the request: … check-part-of-label … check-phase-label` | the workloads pre-date the Kyverno policies going live: their pod templates never carried the mission labels (a patch file that only sets Namespace labels does not set pod-template labels), Argo saw no drift because git lacked the labels too, and the first pod re-creation after a node restart hit the now-live policy (Phase-5-era cert-manager outage; fix in `deploy/phases/01-substrate/cert-manager/cert-manager-patches.yaml`) | add the labels to the pod templates in git, replay the owning tree (§9.4 byte-identity), and extend the negative test: a policy that only ever evaluated pre-existing pods proves nothing — the deny-proof must create a pod |

## 13. Upgrade & rollback

- **Platform (k3s):** pin the k3s version per node; upgrade one node at a time with the data plane
  replicated (CNPG replicas, single-broker Kafka acknowledged as single-node risk, ADR-006).
- **Applications:** git tag per release (`release/YYYY-MM-DD`); rollback = `git revert` or retag the
  app-of-apps to the previous tag + sync. Argo rollback history is a last resort only (I-1).
- **Schema:** migrations are append-only and idempotent; never edit an applied migration — write
  `002_*.sql` forward.
