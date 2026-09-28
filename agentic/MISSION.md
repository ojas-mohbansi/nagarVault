# MISSION: Build NagarVault — 7-Day Execution Mandate

> **Usage:** Feed this file (or paste its contents) to the executing coding agent. It is
> self-sufficient by design: the agent needs zero prior knowledge of this repository.
> Companion rulebook: [`../AGENTS.md`](../AGENTS.md) — the mission operates strictly inside it.

---

You are the build agent for NagarVault, an air-gapped, privacy-first civic data operating layer.
Your mission: read this repository's documentation suite, then implement the platform end-to-end —
**Phases 1 through 10** of [`docs/PHASES.md`](../docs/PHASES.md) — across a minimum seven-day
execution window. Phase 0 (the documentation suite) is already complete and is your blueprint.

You are fully empowered. Success is a running, self-healing, parity-verified Kubernetes deployment
of every component, evidenced in a mission log, with the repository left cleaner than you found it.

---

## 1. Mandatory onboarding (before you touch anything — Day 0)

Read in this exact order; do not skip or reorder:

1. [`AGENTS.md`](../AGENTS.md) — invariants I-1…I-12, system map, agent protocol, "never do" list.
2. [`docs/PHASES.md`](../docs/PHASES.md) — your contract: charters, exit criteria, rollback doctrine.
3. [`docs/CONVENTIONS.md`](../docs/CONVENTIONS.md) — naming, port registry, label schema.
4. [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) — flows, endpoint/topic/storage registries.
5. [`docs/SECURITY.md`](../docs/SECURITY.md) — boundaries you must not cross.
6. [`docs/OPERATIONS.md`](../docs/OPERATIONS.md) — procedures you will follow, not invent.
7. [`docs/DECISIONS.md`](../docs/DECISIONS.md) — the 12 ADRs. If your change contradicts one,
   stop and write a superseding ADR first.
8. Skim every service directory and the frozen `docker-compose.yml` to ground yourself in real
   behavior: `authService/`, `adminService/`, `enrichWorker/` (+ `migrations/`), `queryService/`,
   `slmService/`, `schemaIndexer/`, `nagar-vault-backend/`, `frontend/`, `nagar-vault-ui/`.

Then produce `agentic/mission-log.md` with: an onboarding summary (prove you understood the
system in your own words), a phase-by-phase execution plan mapped to the Day grid below, an
environment audit (what tooling exists where you run), and a risk list. **No implementation before
this file exists.**

## 2. Mission timeline

Days are targets, not walls — slip but never skip a gate. A phase is "done" only when its exit
criteria (PHASES.md §1/§2) are met and evidenced.

| Day | Phases | Non-negotiable gate |
|---|---|---|
| 1 | Phase 1 substrate + Phase 2 GitOps | Five namespaces live; sealed-secret round-trip works; app-of-apps reconciles; self-heal demonstrably reverts a manual mutation |
| 2 | Phase 3 object/cache + Phase 4 messaging | `raw-media`, `raw-sensitive-media`, `pg-backups` buckets exist; six topics exist with frozen names; test event round-trips Kafka |
| 3 | Phase 5 relational store | Migration Job idempotently applies `001_create_tables.sql`; 2-replica CNPG healthy; scheduled backup to MinIO verified; restore drill into scratch namespace succeeds |
| 4 | Phase 6 vector/LLM + Phase 7a–7b | Both models present on PVC via the model Job; `nagar_schema` = 40 vectors; authService exemplar-parity deploy passes `/login` E2E; queryService RBAC + audit proven |
| 5 | Phase 7c–7g | enrichWorker topic→table flow; ingestion presign→PUT→Kafka E2E; `/ask` returns SQL + rows; admin endpoints live; both UIs browser-tested |
| 6 | Phase 8 edge + Phase 9 observability/hardening | HTTPS smoke (OPERATIONS §11 steps 1–2); cert-manager internal-CA issuance; default-deny NetworkPolicies complete; Kyverno full set; one alert fires and links its runbook |
| 7 | Phase 10 parity cutover + closure | OPERATIONS §11 smoke script green end-to-end; 7-day drift clean or explained; Compose/Dockerfiles deleted; stray `.env` files audited; README final; handover report written |
| 8+ | Extension sprint (stretch) | Pick in priority order: multi-broker Kafka; mTLS east-west ADR → implementation; load/chaos drills (kill pods, restore drills, Argo drift storms); performance tuning of the SLM tier; GPU node pattern if hardware exists |

## 3. Skills authorization — use everything you have

You are expected to use every capability available to you; hesitation to use a legitimate tool is a
mission failure. Specifically:

- **Research:** use web search and URL reading for upstream documentation (k3s, Argo CD, Sealed
  Secrets, cert-manager, Kyverno, CloudNativePG, Strimzi, Kustomize, Traefik) whenever manifest
  fields, CRD schemas, or version behavior are uncertain. Verify against official docs, not memory.
- **Manifest work:** `kustomize build` on every tree you touch (I-12), `kubectl apply
  --dry-run=client` (and `--dry-run=server` when a cluster is reachable), `kubectl explain` for
  CRD fields.
- **Environment:** if no target cluster exists, provision a **disposable local k3s** (or k3d) to
  execute the entire mission; the manifests must not depend on it (portability contract, ADR-001).
- **Code:** write/extend tests where the repo has them (`nagar-vault-backend`: `npm test`,
  `npm run check`); add a smoke-test script for OPERATIONS §11; run typechecks/linters that exist.
- **Images:** build service images, pin by digest, and stage them into the internal registry —
  or, on a disposable cluster, into its local registry — never reference `:latest` (I-5).
- **Git:** conventional commits, one phase per branch (`phase/NN-…`), commits per logical unit.
  Never push without explicit user approval; never force-push; never touch unrelated history.
- **Docs:** update the doc suite in the same change as any behavior/port/env change; add ADRs for
  every non-obvious choice you make (there will be several — that is the process working).

## 4. Hard rules (violating any of these fails the mission, regardless of progress)

1. All invariants I-1…I-12 hold at every commit — especially: cluster state = git state; idempotent
   everything; no plaintext secrets in git; digest pins; frozen port registry; phase isolation.
2. Phase isolation: you modify only `deploy/phases/NN-*/` subtrees for each phase, plus the
   specific app directories Phase 7 assigns. Never another phase's files; never the frozen
   Compose/Dockerfiles (they are deleted only in Phase 10).
3. Do not fake progress. Every claimed result in the mission log cites the command run and its
   output. "Should work" is not done. A red gate honestly reported beats a green lie.
4. Stop-and-escalate conditions: a fix would contradict an ADR/invariant; you need credentials or
   hardware you don't have; a destructive action (deleting PVCs, resetting the cluster) becomes
   necessary; two consecutive gate failures on the same phase. Escalate in the mission log with
   your recommended option, then continue with the best safe alternative.
5. Destructive or irreversible commands (cluster resets, volume deletion, registry purges) require
   explicit user approval in the moment — never bundle them into quiet automation.
6. If the plan itself proves wrong, the correct move is: write a superseding ADR, update
   PHASES.md, then implement — never silent deviation.

## 5. Evidence & reporting protocol

Maintain `agentic/mission-log.md` as an append-only journal:

- **Per phase:** entry/exit checklist (quoting PHASES.md criteria), commands + outputs, deviations
  + ADRs written, rollback instructions tested or reviewed.
- **Daily:** a short standup block — done / blocked / next / risks.
- **Final (Day 7):** handover report — what is deployed, how to verify in 10 commands, known gaps,
  extension-sprint recommendations, and a restart-from-scratch runbook (the ultimate zero-maintenance
  test: a fresh operator must be able to rebuild everything from git + docs alone).

## 6. Mission exit criteria (all must hold)

- [ ] Every phase 1–10 marked Done in the PHASES.md status ledger with evidence links.
- [ ] OPERATIONS §11 smoke script green over HTTPS on the (disposable or target) cluster.
- [ ] Parity checklist (PHASES.md §2 Phase 10) fully signed, including: RBAC enforced, PII
      denylist enforced, DLQ inspectable, backup restore drill succeeded, Argo drift-free.
- [ ] `kustomize build` clean across the whole `deploy/` tree; zero Kyverno violations.
- [ ] Compose files and per-service Dockerfiles deleted; legacy `.env` audit recorded;
      `frontend/frontend/` duplicate resolved.
- [ ] Doc suite updated to describe reality (no aspiration stated as fact).
- [ ] All ADRs written; mission log complete; handover report delivered.

Begin with onboarding. Work in phase order. Use everything at your disposal. Leave behind a
system that heals itself and documentation that needs no author standing next to it.
