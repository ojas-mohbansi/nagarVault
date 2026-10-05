# schemaIndexer test suite — Phase 6 (hermetic; no Qdrant, no Ollama, no network).
#
# COVERAGE UNDER TEST (ADR-021 provisioning, ADR-028 reindex):
#   * doc_point_id is deterministic and stays inside Qdrant's UNSIGNED point-id domain.
#     The original signed fold produced negatives and Qdrant rejected them
#     ("value ... is not a valid point ID"), so this is a regression test, not a tautology.
#   * load_docs reads schema_docs.json, rejects duplicate ids, and every document carries
#     the `table` field slmService relies on to label retrieved context.
#   * sync() wires the pieces together and is idempotent: two passes over the same corpus
#     must produce the same point ids and the same document count.
#   * sync() refuses to report success when the collection cannot serve a search afterwards.
#
# The module-level seams (embed_batch, upsert_points, collection_info, search_ok,
# ensure_collection, wait_for_dependencies) are monkeypatched, matching the pattern the
# Phase-7 suites use. The REAL path is proven in-cluster (G10.1).
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import index as ix  # noqa: E402

# schema_docs.json lives beside the indexer, not inside it: the Job mounts it
# into /app and the indexer reads it from SCHEMA_DOCS_PATH at runtime.
SCHEMA_DOCS = Path(__file__).resolve().parents[2] / "schema" / "schema_docs.json"


@pytest.fixture()
def docs_path(monkeypatch):
    monkeypatch.setattr(ix, "SCHEMA_DOCS_PATH", str(SCHEMA_DOCS))
    return SCHEMA_DOCS


# --------------------------------------------------------------- deterministic point ids


def test_doc_point_id_is_deterministic():
    assert ix.doc_point_id("nmc_complaints:columns") == ix.doc_point_id("nmc_complaints:columns")


def test_doc_point_ids_are_distinct():
    ids = {ix.doc_point_id(f"doc-{i}") for i in range(1000)}
    assert len(ids) == 1000


def test_doc_point_id_fits_qdrants_unsigned_domain():
    """Qdrant rejects negative point ids. A signed fold silently produced them and the
    whole Job failed at the upsert, so the domain is asserted, not assumed."""
    for name in ["a", "nmc_complaints:columns", "traffic_events:summary", "zzz"]:
        pid = ix.doc_point_id(name)
        assert isinstance(pid, int)
        assert 0 <= pid < 2**64, f"{name} -> {pid} is outside the u64 domain"


# --------------------------------------------------------------------------- load_docs


def test_load_docs_reads_the_committed_corpus(docs_path):
    docs = ix.load_docs()
    assert len(docs) > 0
    for d in docs:
        assert d["id"] and d["text"]


def test_load_docs_rejects_duplicate_ids(monkeypatch, tmp_path):
    bad = {"documents": [{"id": "x", "text": "one", "table": "t"},
                         {"id": "x", "text": "two", "table": "t"}]}
    f = tmp_path / "dupes.json"
    f.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(ix, "SCHEMA_DOCS_PATH", str(f))
    with pytest.raises(SystemExit):
        ix.load_docs()


def test_every_document_carries_the_table_key(docs_path):
    """slmService reads `doc.get("table")` off the Qdrant payload and renders
    `[table: <name>]` or, when it is null, `[schema overview]` (the Phase-7d fix). The
    payload contract is that the KEY exists on every document: a document missing it
    entirely is indistinguishable from an overview doc and silently loses its attribution.
    Overview and sql-style documents legitimately carry table=null, so the value is
    allowed to be None here."""
    docs = ix.load_docs()
    missing = [d["id"] for d in docs if "table" not in d]
    assert missing == [], f"documents missing the table key: {missing}"
    bogus = [d["id"] for d in docs
             if d["table"] is not None and not isinstance(d["table"], str)]
    assert bogus == [], f"documents with a non-string table: {bogus}"
    # And the unattributed set must stay small: if every document were null the SLM could
    # not attribute any context to a table at all.
    attributed = [d for d in docs if d["table"]]
    assert attributed, "no document is attributed to a table"


# --------------------------------------------------------------------------------- sync


@pytest.fixture()
def wired(monkeypatch):
    """Wire sync() to in-memory fakes and record every upsert it performs."""
    seen: list[dict] = []

    def fake_embed(texts):
        return [[0.01 * (i + 1)] * ix.EXPECTED_DIM for i, _ in enumerate(texts)]

    def fake_upsert(docs, vectors):
        seen.append({"docs": list(docs), "vectors": list(vectors)})
        return len(docs)

    monkeypatch.setattr(ix, "wait_for_dependencies", lambda *a, **k: None)
    monkeypatch.setattr(ix, "embed_batch", fake_embed)
    monkeypatch.setattr(ix, "ensure_collection", lambda dim: None)
    monkeypatch.setattr(ix, "upsert_points", fake_upsert)
    monkeypatch.setattr(ix, "collection_info", lambda: {"points_count": len(seen[-1]["docs"]) if seen else 0})
    monkeypatch.setattr(ix, "search_ok", lambda vector=None: True)
    return seen


def test_sync_indexes_every_document(docs_path, wired):
    summary = ix.sync()
    assert summary["documents"] == len(ix.load_docs())
    assert summary["upserted"] == summary["documents"]
    assert summary["dim"] == ix.EXPECTED_DIM


def test_sync_is_idempotent(docs_path, wired):
    """Re-running the indexer must converge, not accumulate or drift."""
    first = ix.sync()
    second = ix.sync()
    assert first["documents"] == second["documents"]
    assert first["upserted"] == second["upserted"]
    ids_first = [ix.doc_point_id(d["id"]) for d in wired[0]["docs"]]
    ids_second = [ix.doc_point_id(d["id"]) for d in wired[1]["docs"]]
    assert ids_first == ids_second


def test_sync_refuses_a_wrong_dimensionality_embedding(docs_path, wired, monkeypatch):
    """A model that silently returns the wrong vector width must fail loudly rather than
    write a collection the slmService cannot search."""
    monkeypatch.setattr(ix, "embed_batch", lambda texts: [[0.0] * 8 for _ in texts])
    with pytest.raises(SystemExit):
        ix.sync()


def test_sync_fails_when_the_collection_cannot_be_searched(docs_path, wired, monkeypatch):
    """The read-after-write witness: a rebuild that leaves the collection unsearchable is a
    failed recovery, not a success with a stale count (ADR-028)."""
    monkeypatch.setattr(ix, "search_ok", lambda vector=None: False)
    with pytest.raises(RuntimeError):
        ix.sync()
