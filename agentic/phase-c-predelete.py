# Phase C pre-delete computation (read-only) — curl(--noproxy)+line-parser revision.
import glob
import json
import re
import subprocess

ACCEPT = ("application/vnd.oci.image.manifest.v1+json, "
          "application/vnd.oci.image.index.v1+json, "
          "application/vnd.docker.distribution.manifest.v2+json, "
          "application/vnd.docker.distribution.manifest.list.v2+json")
BASE = "http://localhost:35000"
CURL = ["curl", "-s", "--noproxy", "*", "--max-time", "10"]


def curl_json(path):
    out = subprocess.run(CURL + ["-H", f"Accept: {ACCEPT}", BASE + path],
                         capture_output=True, text=True, timeout=20).stdout
    return json.loads(out)


def curl_head_digest(path):
    out = subprocess.run(CURL + ["-I", "-H", f"Accept: {ACCEPT}", BASE + path],
                         capture_output=True, text=True, timeout=20).stdout
    for line in out.splitlines():
        if line.lower().startswith("docker-content-digest:"):
            return line.split(":", 1)[1].strip()
    return ""


def curl_body(path):
    return subprocess.run(CURL + ["-H", f"Accept: {ACCEPT}", BASE + path],
                          capture_output=True, text=True, timeout=20).stdout


# ---------- 1. in-tree referenced digests (structure-independent keep set) ----------
# Deletion safety needs only the SET of digests git references — regardless of the
# kustomize entry shape (name+newName+digest, or bare name+digest in phase-1).
pins = {}          # newName-keyed pairs (for the record)
bare_digests = set()
raw_files = sorted(glob.glob("deploy/phases/*/digest-pins/kustomization.yaml"))
for path in raw_files:
    text = open(path, encoding="utf-8").read()
    bare_digests.update(re.findall(r"digest:\s*(sha256:[0-9a-f]{64})", text))
    cur = {}
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if s.startswith("- name:"):
            if cur.get("newName") and cur.get("digest"):
                pins[cur["newName"]] = cur["digest"]
            cur = {}
        elif s.startswith("newName:"):
            cur["newName"] = s.split(":", 1)[1].strip()
        elif s.startswith("digest:"):
            m = re.fullmatch(r"sha256:[0-9a-f]{64}", s.split(":", 1)[1].strip())
            if m:
                cur["digest"] = s.split(":", 1)[1].strip()
    if cur.get("newName") and cur.get("digest"):
        pins[cur["newName"]] = cur["digest"]

pin_digests = sorted(bare_digests)   # THE keep set: every digest git references
print(f"PIN FILES        : {len(raw_files)}")
print(f"PIN PAIRS        : {len(pins)} newName-keyed; referenced digests: {len(pin_digests)}")
for k in sorted(pins):
    print(f"   pin {k.split('/mission/')[-1]:28s} -> {pins[k][:20]}…")

# ---------- 2. registry inventory ----------
repos = curl_json("/v2/_catalog")["repositories"]
inv = {}
for repo in repos:
    tags = (curl_json(f"/v2/{repo}/tags/list") or {}).get("tags") or []
    entries = []
    for tag in tags:
        try:
            dig = curl_head_digest(f"/v2/{repo}/manifests/{tag}")
            if not dig:
                dig = "ERROR:NoDigestHeader"
        except Exception as e:  # noqa: BLE001
            dig = f"ERROR:{type(e).__name__}"
        entries.append({"tag": tag, "digest": dig})
    inv[repo] = entries
total_tags = sum(len(v) for v in inv.values())
print(f"REGISTRY         : {len(repos)} repositories, {total_tags} tags")

# ---------- 3. classify ----------
pinned_children = set()
anomalies = []
for repo, entries in inv.items():
    full = f"k3d-nagar.localhost:5000/{repo}"
    for e in entries:
        d = e["digest"]
        if d.startswith("ERROR:"):
            anomalies.append(f"{full}:{e['tag']} resolve-failed ({d}); left in place")
            continue
        if d in pin_digests:
            continue
        try:
            body = json.loads(curl_body(f"/v2/{repo}/manifests/{d}"))
        except Exception as ex:  # noqa: BLE001
            anomalies.append(f"{full}:{e['tag']} fetch-failed ({type(ex).__name__}); left in place")
            continue
        media = body.get("mediaType", "")
        if "index" in media or "list" in media:
            kept = [m["digest"] for m in body.get("manifests", []) if m["digest"] in pin_digests]
            if kept:
                pinned_children.update(kept)
                e["protected_index"] = True

keep_digests = set(pin_digests) | pinned_children

delete_plan = []
pinned_tags = []
protected = []
for repo, entries in inv.items():
    full = f"k3d-nagar.localhost:5000/{repo}"
    for e in entries:
        d = e["digest"]
        rec = {"repo": repo, "tag": e["tag"], "digest": d}
        if d.startswith("ERROR:"):
            continue
        if d in pin_digests:
            pinned_tags.append(rec)
        elif e.get("protected_index"):
            protected.append(rec)
        elif d in keep_digests:
            anomalies.append(f"{full}:{e['tag']} is a pinned index child; kept")
        else:
            delete_plan.append(rec)

where = {d: [] for d in pin_digests}
for repo, entries in inv.items():
    for e in entries:
        if e["digest"] in where:
            where[e["digest"]].append(f"{repo}:{e['tag']}")
unresolvable = sorted(d for d, v in where.items() if not v)
for d in unresolvable:
    anomalies.append(f"PINNED DIGEST UNRESOLVABLE in registry: {d} — nothing deleted anywhere")

print(f"KEEP             : {len(pin_digests)} pinned digests + {len(pinned_children)} protected children")
print(f"TAGS KEPT        : {len(pinned_tags)} pinned-at + {len(protected)} protected-index")
print(f"TAGS TO DELETE   : {len(delete_plan)}")
print(f"ANOMALIES        : {len(anomalies)} (all left in place)")
for a in anomalies:
    print(f"  ! {a}")

plan = {
    "pins": pins,
    "pin_digests": pin_digests,
    "pinned_children": sorted(pinned_children),
    "keep_digests": sorted(keep_digests),
    "inventory": inv,
    "pinned_tags": pinned_tags,
    "protected": protected,
    "delete_plan": delete_plan,
    "anomalies": anomalies,
    "unresolvable_pins": unresolvable,
}
with open("agentic/phase-c-plan.json", "w", encoding="utf-8") as f:
    json.dump(plan, f, indent=1)
with open("agentic/phase-c-tagmap.txt", "w", encoding="utf-8") as f:
    for repo in sorted(inv):
        for e in sorted(inv[repo], key=lambda x: x["tag"]):
            mark = ("KEEP-PIN  " if e["digest"] in pin_digests else
                    "KEEP-IDX  " if e["digest"] in pinned_children else
                    "DELETE    ")
            f.write(f"{mark} {repo}:{e['tag']} -> {e['digest']}\n")
print("plan written     : agentic/phase-c-plan.json")
print("tag map written  : agentic/phase-c-tagmap.txt")
