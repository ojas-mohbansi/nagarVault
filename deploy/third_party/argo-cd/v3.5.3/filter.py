#!/usr/bin/env python3
"""Regenerate deploy/third_party/argo-cd/v3.5.3/install.yaml from upstream.

Upstream: https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.3/manifests/install.yaml
Fetched 2026-09-29 (1,917,766 bytes, byte-exact upstream copy saved as
install-upstream.sha256). Transformation (documented per ADR-002, applied ONCE at
vendor time; the committed install.yaml is what Argo deploys):

1. Remove the bundle's `Namespace/argocd` document — we relocate Argo to
   nagar-system (ARCHITECTURE §1) and the namespace already exists (Phase 1).
2. Remove `Deployment/argocd-dex-server` — no external IdP (ADR-008); SSO unused.
   Its Service/Secret/RBAC stay (inert, keeps the bundle diffable).
3. Remove `Deployment/argocd-notifications-controller` — no notification channel
   configured (ADR-011 defers alert routing to Phase 9's Prometheus/Alertmanager).

Usage: python filter.py < upstream-install.yaml > install.yaml
"""
import re
import sys

REMOVED = {
    ("Namespace", "argocd"),
    ("Deployment", "argocd-dex-server"),
    ("Deployment", "argocd-notifications-controller"),
}

text = sys.stdin.read()
out, dropped = [], []
for doc in text.split("\n---\n"):
    kind = re.search(r"^kind: (\w+)$", doc, re.M)
    name = re.search(r"^  name: ([\w.-]+)$", doc, re.M)
    if kind and name and (kind.group(1), name.group(1)) in REMOVED:
        dropped.append(f"{kind.group(1)}/{name.group(1)}")
        continue
    out.append(doc)

print("\n---\n".join(out), end="")
print(f"\n# filtered: removed {len(dropped)} docs: {', '.join(dropped)}",
      file=sys.stderr)
