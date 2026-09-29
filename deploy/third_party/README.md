# Vendored Third-Party Manifests (ADR-002)

Upstream components are **vendored as static manifests** and treated as code — no Helm in the
deployment path (ADR-002). Upgrades are explicit commits of a new version directory; the old
version directory is removed by the same commit.

## Registry

| Component | Version | Source asset | Namespace | Images pinned |
|---|---|---|---|---|
| cert-manager | v1.16.4 | `releases/download/v1.16.4/cert-manager.yaml` (986,843 bytes) | `cert-manager` | 3 (quay.io/jetstack/*) |
| sealed-secrets-controller | v0.28.0 | `releases/download/v0.28.0/controller.yaml` (11,287 bytes) | `nagar-system` | 1 (docker.io/bitnami/sealed-secrets-controller) |
| kyverno | v1.13.4 | `releases/download/v1.13.4/install.yaml` (3,388,412 bytes) | `nagar-system` | 5 (ghcr.io/kyverno/*) |
| strimzi-cluster-operator | 1.2.0 | `releases/download/1.2.0/strimzi-cluster-operator-1.2.0.yaml` | `nagar-system` | 2 (quay.io/strimzi/*) |
| cloudnative-pg | v1.30.1 | `release-1.30/releases/cnpg-1.30.1.yaml` (1,293,413 bytes) | `cnpg-system` | 1 (ghcr.io/cloudnative-pg/cloudnative-pg) |

Vendored date: 2026-09-29. Every file above is byte-identical to its upstream release asset; each
version directory carries an `install-upstream.sha256` naming the exact source URL it was fetched
from, so a reviewer can re-download and re-verify it. The Strimzi row was added in Phase 5 —
Phase 4 vendored the operator but did not update this table, and an incomplete registry is worse
than none (recorded in the mission log rather than quietly corrected).

Namespace column note: the value is where the component *runs*, which is not always a mission
namespace. Two operators are relocated into `nagar-system` (sealed-secrets, strimzi); three stay in
their upstream-native namespace because their bundles ship that namespace and hardcode it
throughout (cert-manager, kyverno, cloudnative-pg). ADR-019 §3 records the per-component reasoning;
Phase 1's log records it for the first three.

## Digest pinning (invariant I-5)

Every image reference above is pinned by digest. The mechanism is a per-phase kustomize
`Component` — `deploy/phases/<phase>/digest-pins/` — which that phase's `kustomization.yaml`
includes, so pins are declared once per phase and apply to every image in its tree:

| Phase | Component | Images pinned |
|---|---|---|
| 1 | `phases/01-substrate/digest-pins/` | 9 (cert-manager, sealed-secrets, kyverno) |
| 2 | `phases/02-gitops/digest-pins/` | 3 (argocd, dex, redis) |
| 3 | `phases/03-object-cache/digest-pins/` | 4 (minio, minio-mc, redis, busybox) |
| 4 | `phases/04-messaging/digest-pins/` | 2 (strimzi-operator, strimzi-kafka) |
| 5 | `phases/05-postgres/digest-pins/` | 2 (cnpg-operator, cnpg-postgresql — the operand doubles as the Jobs' psql client) |

A phase's component is also included by that phase's *operator sub-tree* (e.g. `phases/05-postgres/
cnpg/`), so a subtree build pins its own images; see the components' own headers for the
read-the-digest-back-from-the-registry method (G0.3 note 3 in the mission log explains why the
registry's answer, not docker's local metadata, is the authority).

**Resolution method** (reproducible): `docker manifest inspect <image:tag> -v` → take the first
`digest` entry (the index manifest digest as served by the source registry). Resolved
2026-09-29; re-run the same command to verify a pin against upstream.

## Kyverno restricted-baseline acceptances (SECURITY §5)

The Kyverno v1.13.4 install.yaml runs privileged init/seed containers by design
(`kyvernopre` needs host access to clean webhook artifacts; the webhook-gen Job generates
TLS material). Rather than weaken the cluster-wide baseline, the phase tree
(`deploy/phases/01-substrate/`) patches exactly these two upstream workloads out of the
enforcing policies via `psa-exempt-labels.yaml`, and documents that acceptance here:

1. `kyvernopre` Upgrade/Job hook — runs with root + host access pre-upgrade, upstream design.
2. `kyverno-webhook-gen` Job — generates the webhook's serving certs at install time.

Everything else in the cluster runs under the same three enforcing policies as application
workloads (labels, no-latest, resources). Exemptions are label-scoped to the two named
workloads only and are revisited on every kyverno version bump.

## Why manifest (static) install instead of chart-rendered

ADR-002: raw YAML is diffable and exactly what lands on the cluster. cert-manager and Kyverno
ship first-class static bundles; nothing was lost by not rendering charts.
