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

### Restore drill (quarterly, evidence recorded)
```bash
kubectl -n nagar-platform apply -f <restore-manifest>   # CNPG BootstrapRestore
# then verify row counts vs audit baseline, run the §11 smoke test
```

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

## 13. Upgrade & rollback

- **Platform (k3s):** pin the k3s version per node; upgrade one node at a time with the data plane
  replicated (CNPG replicas, single-broker Kafka acknowledged as single-node risk, ADR-006).
- **Applications:** git tag per release (`release/YYYY-MM-DD`); rollback = `git revert` or retag the
  app-of-apps to the previous tag + sync. Argo rollback history is a last resort only (I-1).
- **Schema:** migrations are append-only and idempotent; never edit an applied migration — write
  `002_*.sql` forward.
