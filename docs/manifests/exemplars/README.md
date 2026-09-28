# Canonical Manifest Exemplars

> Reference shapes for every workload class in NagarVault. Hub: [AGENTS.md](../../../AGENTS.md).
> These are **documentation artifacts**: copy them into `deploy/phases/NN-*/` (Phase 1+) and adapt
> names/digests, never edit them to change policy — policy changes go through ADRs
> ([DECISIONS.md](../../DECISIONS.md)). Live trees must satisfy `kustomize build` (AGENTS.md I-12).

## Index

| File | Workload class | Phase |
|---|---|---|
| [postgres-cnpg.yaml](postgres-cnpg.yaml) | CloudNativePG HA cluster + scheduled WAL/base backups to MinIO | 5 |
| [postgres-migration-job.yaml](postgres-migration-job.yaml) | Idempotent schema migration Job | 5 |
| [kafka-strimzi.yaml](kafka-strimzi.yaml) | Strimzi Kafka (KRaft, single-broker per ADR-006) | 4 |
| [kafka-topics-job.yaml](kafka-topics-job.yaml) | Idempotent topic creation Job (six frozen topics) | 4 |
| [minio-statefulset.yaml](minio-statefulset.yaml) | Object storage StatefulSet + init-container bucket creation | 3 |
| [redis-statefulset.yaml](redis-statefulset.yaml) | Ephemeral cache StatefulSet | 3 |
| [qdrant-statefulset.yaml](qdrant-statefulset.yaml) | Vector store StatefulSet | 6 |
| [ollama-model-job.yaml](ollama-model-job.yaml) | Checksum-pinned model provisioning Job (ADR-010) | 6 |
| [ollama-statefulset.yaml](ollama-statefulset.yaml) | LLM serving StatefulSet + model PVC | 6 |
| [auth-service-deployment.yaml](auth-service-deployment.yaml) | **App-service exemplar** — Deployment + Service + PDB + probes + resources + NetworkPolicy + SealedSecret consumption; the template every Phase 7 micro-phase must match | 7a |

## Mandatory in every exemplar (mirror of AGENTS.md I-4/I-5)

- Labels per [CONVENTIONS.md](../../CONVENTIONS.md) §5 (`app.kubernetes.io/*`, `nagar.io/phase`,
  `nagar.io/tier`).
- Image references pinned `@sha256:` from `registry.nagar.internal:5000`.
- `readinessProbe` + `livenessProbe` hitting real health endpoints.
- Resource `requests` + `limits`.
- `runAsNonRoot`, `seccompProfile: RuntimeDefault`, `allowPrivilegeEscalation: false`,
  `capabilities.drop: [ALL]` (PSS restricted).
- NetworkPolicies with explicit ingress+egress incl. DNS.
- Secrets only via `secretKeyRef` into SealedSecrets ([SECURITY.md](../../SECURITY.md) §6).
- Idempotent init/Job logic (`IF NOT EXISTS`, `--if-not-exists`, checksum guards).
