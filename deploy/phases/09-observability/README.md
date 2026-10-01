# Phase 9 — Observability & hardening

Charter: [PHASES.md §2](../../../docs/PHASES.md) — Prometheus + Loki, full Kyverno set,
NetworkPolicy completion, alert rules with runbook anchors. Exit criteria: dashboards populated;
one alert intentionally fired and linked to its runbook; restore drill evidence recorded.

Everything in this tree is digest-pinned (`digest-pins/`), single-replica, and sized for the
disposable 16 GB substrate. Design rationale and deviations: [ADR-026](../../../docs/DECISIONS.md).

## What runs where

| Object | Namespace | Port | Notes |
|---|---|---|---|
| `nagar-prometheus` | nagar-observability | 9090 | 15 d retention, 8 Gi PVC, rule files with `runbook_url` anchors |
| `nagar-alertmanager` | nagar-observability | 9093 | null receiver (air-gap); the place a firing alert is inspected |
| `nagar-grafana` | nagar-observability | 3300 | provisioned datasources + 2 dashboards; admin password is the SealedSecret `nagar-grafana-admin` |
| `nagar-loki` | nagar-observability | 3100 | filesystem storage, 7 d retention, 5 Gi PVC |
| `nagar-alloy` | nagar-observability | 12345 | tails pod logs **through the API server** (`pods/log`); PSS restricted forbids hostPath, so Promtail cannot run (ADR-026 §3) |
| `nagar-kube-state-metrics` | nagar-observability | 8080 | cluster object state (restarts, waiting reasons) |
| `nagar-kafka-exporter` | nagar-observability | 9308 | `kafka_consumergroup_lag` for the Kafka alert |
| scrape widenings | nagar-system / nagar-platform | 8082 / 9187 | additive NetworkPolicies; no Phase-8/5 manifests edited for them |

Alerts (all five from OPERATIONS §10) live in `prometheus.yaml` → `nagar-prometheus-rules`, each with
`runbook_url: docs/OPERATIONS.md#rb-…` pointing at a real anchor in the troubleshooting matrix.

## Reaching the consoles (operator, in-cluster only)

```bash
kubectl -n nagar-observability port-forward svc/nagar-grafana 3300:3300      # http://127.0.0.1:3300
kubectl -n nagar-observability port-forward svc/nagar-prometheus 9090:9090   # http://127.0.0.1:9090
kubectl -n nagar-observability port-forward svc/nagar-alertmanager 9093:9093 # http://127.0.0.1:9093
# Grafana login: admin / the value of Secret nagar-grafana-admin (sealed; never in git)
```

Nothing in this tier is exposed through Traefik — the edge port map is frozen (CONVENTIONS §4) and
an operator console is not a public surface.

## Gate fixtures

`e2e/fixtures/` holds the versioned objects the phase gate applies and deletes:

- `crashloop-pod.yaml` — the PodCrashLooping drill: applied until the alert fires in Alertmanager
  with its `runbook_url`, then deleted so the alert resolves.
- `policy-violation-pods.yaml` — the Kyverno admission probes (tagged image, upstream registry,
  hostNetwork); each must be denied, and the compliant control pod must be admitted.
