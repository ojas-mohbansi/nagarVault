# Security — NagarVault

> Normative security policy. Hub: [AGENTS.md](../AGENTS.md). Architecture context: [ARCHITECTURE.md](ARCHITECTURE.md) §5.

## 1. Threat model (summary)

| Adversary | Goal | Primary controls |
|---|---|---|
| Curious insider (officer account) | read PII / cross-department data | role RBAC + PII denylist + audit log |
| Malicious payload in uploaded media | code exec on ingestion | API never opens media; MinIO-only storage; MIME allowlist; size caps |
| Compromised pod in nagar-app | pivot to data plane | default-deny NetworkPolicies, least-priv service accounts, non-root containers |
| Stolen session token | impersonate officer | 60-min TTL, jti denylist on logout, `httponly` cookie |
| Supply-chain (image) | run malicious code | digest pinning, SBOM, trivy scan, cosign verify (§7) |
| Config drift / human error | silent weakening | Argo self-heal + Kyverno deny on non-conforming manifests |

## 2. Identity & session chain (implemented today; preserved)

- Credentials verified with **argon2id** (`PasswordHasher`, `argon2-cffi`).
- JWT: HS256 with shared `JWT_SECRET`; required claims `iss=nagar-auth`, `aud=nagar-services`,
  `jti`, `sub`, `role`; **60-minute** expiry.
- Transport: `session_token` cookie, `httponly`, `samesite=lax`, `secure` if `COOKIE_SECURE=true`
  (**must** be true once TLS terminates at the edge — Phase 8).
- Revocation: `POST /logout` records `jti` server-side; protected endpoints reject denylisted jti.
- Login brute force: 5 req/min per IP (enforced in authService; edge rate-limit middleware added
  as defense-in-depth in Phase 8).
- All services sharing the JWT_SECRET must rotate it together (§6.4).

## 3. Authorization model

| Role | Tables | Notes |
|---|---|---|
| `nmc_officer` | nmc_complaints, traffic_events, water_sensor_readings, ev_bus_telemetry | no health data |
| `ROLE_HEALTH_OFFICER` | + `health_camp_records` | only role that may touch health records |
| admin | users, audit logs, DLQ, resync | via adminService endpoints only |

Enforcement is layered:
1. queryService parses SQL with **sqlglot**, rejects non-SELECT, injects role filters, enforces the
   table-role matrix and the PII column denylist (`name, phone, email, address, aadhaar`).
   **Two independent layers, per ADR-030:** the AST gate proves the projection column-by-column
   (a whole-row reference or a `*` over a PII table is refused, not just a denylisted name), and
   the database independently refuses to return a denylisted column at all — migration
   `002_pii_column_grants.sql` grants the officer roles `SELECT` per non-PII column rather than
   on the table. A denial from either layer is an audited `blocked` verdict, never a 5xx.
2. Every attempt (allowed or blocked, with reason) is written to `audit_logs`.
3. Postgres-level grants exist as a second wall (target state, Phase 5): the app role keeps only
   SELECT on its allowed tables.

The SLM path (`slmService /ask`) inherits all of the above because generated SQL must pass the same
queryService gate before execution — the LLM has no direct database access.

## 4. Data classification & PII

| Class | Examples | Storage | Leaving the cluster? |
|---|---|---|---|
| Restricted | complaint media in `raw-sensitive-media`, health records, PII columns | MinIO / Postgres | never |
| Internal | civic event payloads, warehouse rows | Postgres | never |
| Public-ish | schema docs (table/column names) | Qdrant | never (schema *names* only are embedded) |

Embeddings are built from `schema_docs.json` (schema documentation), never from citizen data.

## 5. Workload security (Kyverno-enforced, Phase 1+)

- Pod Security Standards **restricted** namespace-wide: `runAsNonRoot`, `seccompProfile:
  RuntimeDefault`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, read-only
  rootFilesystem where the image permits.
- Dedicated ServiceAccount per workload; `automountServiceAccountToken: false` unless the workload
  talks to the API server (none do today).
- Image pulls only from `registry.nagar.internal:5000` (Kyverno registry allowlist + digest pinning — both
  **enforced** since Phase 9 in `nagar-app`/`nagar-observability`, audit-mode in `nagar-platform` where the
  vendored CNPG operator still rides a tagged upstream image). `verifyImages`/cosign stays deferred: no image
  is signed until the Phase 10 supply-chain pass, and an attestor policy over unsigned images would block
  every pod (ADR-026 §3).
- Resource limits mandatory (Kyverno), preventing noisy-neighbor denial of service.

## 6. Secrets management (Sealed Secrets)

### 6.1 Workflow
1. Operator encrypts locally: `kubeseal < secret.yaml > sealed-secret.yaml` (scope:
   namespace+name strict).
2. Only the SealedSecret is committed. The plaintext secret file stays outside git (shred after use).
3. Argo CD applies; the controller decrypts into a native Secret; pods consume via `secretKeyRef`.

### 6.2 SealedSecret → Secret key map (single source of truth)

| SealedSecret (ns) | Key | Consumed by |
|---|---|---|
| `nagar-jwt` (nagar-app) | `jwtSecret` → `JWT_SECRET` | auth, admin, query, slm, ingestion |
| `nagar-postgres-app` (nagar-app) | `databaseUrl` → `DATABASE_URL` | auth, admin, query, enrich |
| `nagar-minio` (nagar-app) | `accessKey`, `secretKey` | ingestion |
| `nagar-registry-pull` (all) | dockerconfigjson | imagePullSecrets |

### 6.3 Prohibitions
- No `stringData`/`data` literals in any committed Secret. CI/ Kyverno rejects.
- No secret values in logs, error messages, docs, or ADRs.
- No `.env` files under version control. (Audit stray tracked `.env` files in Phase 10 — the repo
  currently has several legacy, likely-stale per-service `.env` files; they must be reviewed then.)

### 6.4 Rotation
JWT_SECRET, Postgres password, and MinIO keys are rotated by re-sealing + re-applying the
SealedSecret, then rolling the dependent Deployments (Argo does this on sync). CNPG supports
password rotation without downtime via its user management. Model/data loss is not possible through
secret rotation.

## 7. Supply chain

- Base images and app images pinned **by digest** (`@sha256:...`), never `:latest` (violates I-5).
- CI (per phase, not yet built): build → `syft` SBOM artifact → `trivy image --exit-code 1 --severity
  CRITICAL,HIGH` gate → `cosign sign` → push to internal registry. Air-gap: all tools run on the
  build host; the cluster only ever pulls from the internal registry and verifies cosign signatures
  via Kyverno at admission.
- Model weights are checksum-pinned in the Ollama model Job (exemplar: `ollama-model-job.yaml`).

## 8. Network policy model

Base posture: **default deny** in `nagar-app`, `nagar-platform`, and ingress from Traefik only.

Ordered rules mirroring [ARCHITECTURE.md](ARCHITECTURE.md) §4.4:
- frontend → ingestion, slm, auth (HTTP)
- browser → MinIO presigned PUT via edge route
- ingestion → MinIO, Redis, Kafka
- enrichWorker → Kafka, Postgres
- auth/admin/query → Postgres; admin → Kafka, schemaIndexer
- slm → Ollama, Qdrant, queryService; schemaIndexer → Ollama, Qdrant
- DNS (kube-system CoreDNS) allowed everywhere — always include it or everything breaks
- kafka-exporter → Kafka `PLAIN-29092`, scoped to that ONE pod on both sides: the exporter
  carries its own egress rule, and the broker's ingress rule in `deploy/phases/04-messaging/`
  admits `nagar-observability` **with a podSelector**, so Grafana/Loki/Alloy/Prometheus gain no
  access to the broker. NetworkPolicy is evaluated on both ends of a connection — widening only
  the exporter's egress half is not enough (this was the exporter's crash-loop, OPERATIONS §12.19)
- observability ingresses: Prometheus scrapes the pod endpoints it discovers (Phase 9 jobs:
  kube-state-metrics :8080, cert-manager :9402, Traefik edge :8082, CNPG instance-manager :9187,
  kafka-exporter :9308, Alertmanager :9093); Alloy is the only pod allowed to `GET pods/log`; Loki/Loki-push
  and Grafana→datasources stay namespace-local. The app-tier convention (pods labeled
  `nagar.io/scrape: "true"` serving `/metrics` on 9090) is **declared but not yet fulfilled** — no mission
  service exposes metrics today, which is why `Ingest5xxRate` is derived from the edge (ADR-026 §3)

Egress: denied by default except listed targets + DNS + internal registry. No internet egress is
required at runtime (air-gap).

## 9. Tenancy & boundaries

- Single-tenant cluster, dedicated hardware, air-gapped room. Multi-tenancy is out of scope (ADR-008).
- Node trust: cluster admin == platform owner. No untrusted multi-tenant workloads on the cluster.

## 10. Audit & evidence

- `audit_logs` table: every SQL attempt — actor, role, SQL, verdict, block reason, rows, IP, time.
- Argo CD keeps a full application history + sync diffs (platform-level audit of config changes).
- Kyverno policy violations are admission-denied and reported via Kyverno's own reports-controller
  (`kubectl get policyreport -A`, plus the controller's `/metrics`); the optional `policy-reporter` UI was
  not deployed in Phase 9 — a documented follow-up, not a gap in coverage (ADR-026 §3).
- Backups are encrypted MinIO objects; restore drills (OPERATIONS §8) are the evidence that the
  security posture survives recovery.
