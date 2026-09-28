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

Vendored date: 2026-09-29. The three files are byte-identical to the upstream release assets.

## Digest pinning (invariant I-5)

Every image reference above is pinned by digest through
[`../phases/01-substrate/digest-pins.yaml`](../phases/01-substrate/digest-pins.yaml) — a
kustomize `Component` that each consuming phase's `kustomization.yaml` includes, so the pins are
applied uniformly and can never drift per phase.

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
