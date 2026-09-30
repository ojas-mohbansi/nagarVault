# Phase C deletion executor: consumes agentic/phase-c-plan.json (the committed,
# evidence-first delete plan) and performs registry DELETEs against the one-shot
# registry with DELETE enabled. Tag-level unlink first, then digest delete.
# Aborts on any unexpected status; 404 on digest delete is tolerated (already gone).
import json
import subprocess
import sys

BASE = "http://127.0.0.1:35100"
plan = json.load(open("agentic/phase-c-plan.json", encoding="utf-8"))
todo = plan["delete_plan"]
print(f"executing {len(todo)} deletions")

done, missing, errors = 0, 0, []
for rec in todo:
    repo, tag, dig = rec["repo"], rec["tag"], rec["digest"]
    if dig.startswith("ERROR:"):
        continue
    r1 = subprocess.run(["curl", "-s", "--noproxy", "*", "-o", "/dev/null", "-w", "%{http_code}",
                         "-X", "DELETE", f"{BASE}/v2/{repo}/manifests/{tag}"],
                        capture_output=True, text=True, timeout=30)
    r2 = subprocess.run(["curl", "-s", "--noproxy", "*", "-o", "/dev/null", "-w", "%{http_code}",
                         "-X", "DELETE", f"{BASE}/v2/{repo}/manifests/{dig}"],
                        capture_output=True, text=True, timeout=30)
    c1, c2 = r1.stdout.strip(), r2.stdout.strip()
    if c2 in ("202", "404"):
        if c2 == "202":
            done += 1
        else:
            missing += 1
    else:
        errors.append(f"{repo}:{tag} digest-delete http={c2}")
        print(f"  ERROR {repo}:{tag} tag={c1} digest={c2}")
        break

print(f"digest-deletes accepted: {done}, already-gone(404): {missing}, errors: {len(errors)}")
sys.exit(1 if errors else 0)
