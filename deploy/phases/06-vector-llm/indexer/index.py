# schemaIndexer — embeds schema_docs.json into Qdrant (ADR-013 rebuild; contract per
# ARCHITECTURE §4.1: port 4005, POST /reindex rebuilds the collection, idempotent).
#
# One codebase, two run modes (PHASES.md §2 Phase 6: "schemaIndexer Job + Deployment"):
#   * Job  (python /app/index.py --once)  — runs at deploy time and on every spec change:
#     ensure collection -> embed all docs -> upsert -> print SUMMARY -> exit.
#   * Deployment (python /app/index.py)   — long-running API on :4005 serving
#     GET /health and POST /reindex (adminService /vector/resync calls this via Phase 7f).
#
# Idempotency (I-2): point IDs are deterministic (sha256 of the document id, folded into a
# signed 63-bit int), so a re-run overwrites its own points instead of duplicating them; the
# collection is created only if absent or mis-configured; re-running /reindex twice yields the
# same point count.
import hashlib
import json
import os
import sys
import time

import httpx

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant.nagar-platform.svc.cluster.local:6333")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama.nagar-platform.svc.cluster.local:11434")
COLLECTION = os.environ.get("COLLECTION", "nagar_schema")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
SCHEMA_DOCS_PATH = os.environ.get("SCHEMA_DOCS_PATH", "/app/schema_docs.json")
PORT = int(os.environ.get("PORT", "4005"))

EXPECTED_DIM = 1024  # bge-m3; verified against the live model at sync time, not trusted blindly


def log(msg: str) -> None:
    print(f"[indexer] {msg}", flush=True)


def doc_point_id(doc_id: str) -> int:
    """Deterministic point id: same document id always maps to the same Qdrant point.

    Qdrant accepts UNSIGNED integers (or UUIDs) as point ids — the original signed fold
    produced negatives, which qdrant rejects with 'Format error in JSON body: value … is
    not a valid point ID' (found by reproducing the Job's exact batch from the indexer
    Deployment pod). u64 keeps the id deterministic AND collision-free at mission scale
    (birthday bound ~5 billion docs)."""
    return int.from_bytes(hashlib.sha256(doc_id.encode()).digest()[:8], "big", signed=False)


def load_docs() -> list[dict]:
    with open(SCHEMA_DOCS_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    docs = raw["documents"]
    ids = [d["id"] for d in docs]
    if len(ids) != len(set(ids)):
        raise SystemExit("[indexer] FATAL: duplicate document ids in schema_docs.json")
    return docs


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed via Ollama /api/embed (batch); fall back to per-doc /api/embeddings."""
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/embed", json={"model": EMBED_MODEL, "input": texts}, timeout=300)
        r.raise_for_status()
        out = r.json().get("embeddings") or []
        if len(out) == len(texts):
            return out
        raise RuntimeError(f"unexpected /api/embed response: {len(out)} embeddings for {len(texts)} inputs")
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            raise
        log("/api/embed not available (404); falling back to per-doc /api/embeddings")
        vecs = []
        for t in texts:
            r = httpx.post(f"{OLLAMA_URL}/api/embeddings", json={"model": EMBED_MODEL, "prompt": t}, timeout=300)
            r.raise_for_status()
            vecs.append(r.json()["embedding"])
        return vecs


def qdrant_ok() -> bool:
    return httpx.get(f"{QDRANT_URL}/healthz", timeout=10).status_code == 200


def collection_info() -> dict | None:
    r = httpx.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=10)
    return r.json()["result"] if r.status_code == 200 else None


def ensure_collection(dim: int) -> None:
    info = collection_info()
    if info is not None:
        size = (info.get("config", {}).get("params", {}).get("vectors") or {}).get("size")
        if size == dim:
            log(f"collection '{COLLECTION}' exists with dim={dim} — keeping it (idempotent re-run)")
            return
        log(f"collection exists with dim={size}, expected {dim} — recreating")
        httpx.delete(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=60).raise_for_status()
    body = {"vectors": {"size": dim, "distance": "Cosine"}}
    httpx.put(f"{QDRANT_URL}/collections/{COLLECTION}", json=body, timeout=60).raise_for_status()
    log(f"collection '{COLLECTION}' created (dim={dim}, Cosine)")


def upsert_points(docs: list[dict], vectors: list[list[float]]) -> int:
    points = [
        {
            "id": doc_point_id(d["id"]),
            "vector": v,
            "payload": {"doc_id": d["id"], "table": d.get("table"), "text": d["text"]},
        }
        for d, v in zip(docs, vectors)
    ]
    # Batch in chunks of 32 to keep request bodies small on the in-cluster link.
    for i in range(0, len(points), 32):
        chunk = points[i : i + 32]
        # wait=true: qdrant upserts are async by default; without this the post-sync
        # points_count witness can read stale and a successful reindex reports a false
        # mismatch (found by the Phase-7d E2E: rebuild landed 40 while /reindex returned 500).
        httpx.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points?wait=true",
            json={"points": chunk},
            timeout=120,
        ).raise_for_status()
    return len(points)


def wait_for_dependencies(timeout_s: int = 300) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if qdrant_ok():
                r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10)
                if r.status_code == 200:
                    return
                log(f"ollama not ready: HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001 - dependency probe, retry until deadline
            log(f"dependency probe failed: {e}")
        time.sleep(5)
    raise SystemExit("[indexer] FATAL: dependencies (qdrant/ollama) not ready within timeout")


def sync() -> dict:
    """One full index pass. Returns a summary dict; safe to run any number of times."""
    wait_for_dependencies()
    docs = load_docs()
    log(f"loaded {len(docs)} schema documents")

    vectors = embed_batch([d["text"] for d in docs])
    dim = len(vectors[0])
    if dim != EXPECTED_DIM:
        raise SystemExit(f"[indexer] FATAL: {EMBED_MODEL} returned dim={dim}, expected {EXPECTED_DIM}")
    log(f"embedded {len(vectors)} documents (dim={dim})")

    ensure_collection(dim)
    count = upsert_points(docs, vectors)

    # Idempotency witness: the point count after the sync.
    info = collection_info()
    points = info.get("points_count") if info else None
    log(f"upserted {count} points; collection now reports points_count={points}")
    return {"documents": len(docs), "upserted": count, "points_count": points, "dim": dim}


def run_once() -> None:
    s = sync()
    print(f"SUMMARY documents={s['documents']} upserted={s['upserted']} points_count={s['points_count']} dim={s['dim']}")
    if s["points_count"] != s["documents"]:
        raise SystemExit("[indexer] FATAL: points_count != documents after sync")
    print("INDEX-SYNC-OK")


def serve() -> None:
    from fastapi import FastAPI

    app = FastAPI(title="schemaIndexer", docs_url=None, redoc_url=None)

    @app.get("/")
    def root() -> dict:
        return {"service": "schemaIndexer", "status": "ok"}

    @app.get("/health")
    def health() -> dict:
        out = {"service": "schemaIndexer", "qdrant": False, "ollama": False, "collection": COLLECTION}
        try:
            out["qdrant"] = qdrant_ok()
            out["ollama"] = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5).status_code == 200
            info = collection_info()
            out["points_count"] = info.get("points_count") if info else 0
            out["healthy"] = out["qdrant"] and out["ollama"] and (out["points_count"] or 0) > 0
        except Exception as e:  # noqa: BLE001 - health endpoint must report, not raise
            out["error"] = str(e)
        return out

    @app.post("/reindex")
    def reindex() -> dict:
        s = sync()
        if s["points_count"] != s["documents"]:
            raise RuntimeError("post-reindex point count mismatch")
        return {"status": "ok", **s}

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        serve()
