# Phase 2 — GitOps control plane

## Topology

```
git (this repo, working tree)
  │  bare mirror staged into the git-repo-mirror image (registry staging model)
  ▼
  Service git-repo-mirror.nagar-system.svc.cluster.local:9418
Application nagar-mission-root  (app-of-apps, path deploy/phases/02-gitops/apps)
  ├── Application nagar-phase1-substrate   → deploy/phases/01-substrate   (ADOPTED live)
  ├── Application nagar-argocd-self        → deploy/phases/02-gitops/argocd
  ├── Application nagar-phase3-object-cache → deploy/phases/03-object-cache (declared, dir empty)
  └── Application nagar-phase4-messaging    → deploy/phases/04-messaging    (declared, dir empty)
```

## One-time bootstrap (the only imperative kubectl this phase ever needs)

Argo CD cannot sync itself before it exists; `deploy/phases/02-gitops/kustomization.yaml`
bootstraps the whole graph in one server-side apply, after which the cluster is owned by git:

```bash
kustomize build --load-restrictor LoadRestrictionsNone deploy/phases/02-gitops \
  | kubectl apply --server-side --force-conflicts -f -
```

Teardown of Argo alone (cluster keeps running): delete the `nagar-argocd-self` and
`nagar-mission-root` Applications + the argocd workloads; everything else is unaffected
(rollback doctrine, PHASES.md §3).

## Git transport (dev/air-gap equivalent of the production remote)

Argo CD reads desired state from **git**, never from a host filesystem, and the k3d Docker
network cannot reach host processes. The production answer (an internal git remote) is
mirrored here: the bare repo is **staged into the `git-repo-mirror` image** — the exact model
of staging images into the internal registry — and served read-only by `git daemon` behind a
Service Argo can resolve:

```bash
# after committing the changes Argo must consume:
git clone --bare "$(git remote get-url origin)" payload/nagarvault.git   # at mission branch
docker build -t k3d-nagar.localhost:5000/mission/git-repo-mirror:<tag> deploy/phases/02-gitops/git-mirror
docker push k3d-nagar.localhost:5000/mission/git-repo-mirror:<tag>
# bump newTag in git-mirror/kustomization.yaml, commit, re-bootstrap (or sync via Argo)
```

On a real cluster this whole subtree is replaced by the authenticated internal git remote
(ADR-014); `sourceRepos`/`repoURL` change, nothing else does.

## Adoption semantics (why no live resource churns)

Phase 1 applied the substrate imperatively; Argo adopts rather than re-creates because:

1. **Server-side apply merges** into existing objects (field-manager ownership changes hands);
   identical desired/live fields produce no patch, no resourceVersion bump, no pod-template
   hash change, no pod churn.
2. **Application sync is not `kubectl apply -f`**: Argo compares desired vs live, applies the
   diff (here: zero), and tracks health. Proven in the mission log (G2.1): pod UIDs identical
   pre/post first sync.
3. `prune: true` only deletes objects **no longer in git**; everything in the phase tree stays.

## Self-heal (the zero-maintenance proof)

Mutate a live object out-of-band (I-1 violation, simulated):

```bash
kubectl -n cert-manager scale deploy/cert-manager --replicas=2
```

Argo detects drift on reconciliation and restores `replicas: 1` — without a human and without a
git change. Mission log G2.2 records the timeline.

## Files

| Path | Purpose |
|---|---|
| `argocd/` | Control plane (vendored, filtered, patched, digest-pinned) |
| `root.yaml` | AppProject `nagar` + app-of-apps `nagar-mission-root` |
| `apps/` | Child Applications — doubles as the app-of-apps source directory |
| `digest-pins/` | Argo image digest pins (I-5) |
