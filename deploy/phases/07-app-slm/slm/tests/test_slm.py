# slmService test suite — Phase 7d (hermetic; no ollama, no qdrant, no queryService).
#
# CONTRACT UNDER TEST (ARCHITECTURE §4.1 endpoint registry; §3.4 NL→SQL guardrails;
# Phase-6 model contract; SECURITY §3 — the LLM path inherits the queryService gate):
#   GET  /         liveness
#   GET  /health   ollama/qdrant/query status (public; 503 when any dependency is down)
#   POST /ask      JWT; embed question (bge-m3) -> RAG top-k from nagar_schema -> prompt with
#                  schema context -> qwen3:1.7b generation (temperature=0, think=false,
#                  stream=false) -> extract SQL -> forward to queryService WITH THE CALLER'S
#                  TOKEN (RBAC inheritance: the LLM never gets its own identity) -> surface
#                  SQL + rows or the gate's verdict.
#
# Seams (module-level, monkeypatched): ollama_embed, qdrant_search, ollama_generate,
# query_forward, jti_is_revoked. The generation REQUEST SHAPE (charter parameters) is tested
# directly via build_generate_request.
import sys
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as slm  # noqa: E402

SECRET = "test-secret-not-a-real-credential"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setattr(slm, "jti_is_revoked", lambda jti: False)
    with TestClient(slm.app) as c:
        yield c


def token(role="nmc_officer", sub="officer-001", jti="jti-1", secret=SECRET, **extra):
    now = int(time.time())
    payload = {"iss": "nagar-auth", "aud": "nagar-services", "sub": sub, "role": role,
               "jti": jti, "iat": now, "exp": now + 600}
    payload.update(extra)
    return pyjwt.encode(payload, secret, algorithm="HS256")


def auth(t):
    return {"Authorization": f"Bearer {t}"}


# --------------------------------------------------------------------------- liveness/health


def test_root_liveness(client):
    assert client.get("/").status_code == 200


def test_health_all_up(monkeypatch, client):
    monkeypatch.setattr(slm, "health_ollama", lambda: True)
    monkeypatch.setattr(slm, "health_qdrant", lambda: True)
    monkeypatch.setattr(slm, "health_query", lambda: True)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ollama": "ok", "qdrant": "ok", "query": "ok"}


def test_health_any_down(monkeypatch, client):
    monkeypatch.setattr(slm, "health_ollama", lambda: True)
    monkeypatch.setattr(slm, "health_qdrant", lambda: False)
    monkeypatch.setattr(slm, "health_query", lambda: True)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["detail"]["qdrant"] == "down"
    assert r.json()["detail"]["ollama"] == "ok"


# --------------------------------------------------------------------------- /ask auth


def test_ask_requires_token(client):
    assert client.post("/ask", json={"question": "x"}).status_code == 401


def test_ask_rejects_garbage_token(client):
    assert client.post("/ask", json={"question": "x"}, headers=auth("junk")).status_code == 401


def test_ask_rejects_wrong_audience(client):
    t = token(aud="elsewhere")
    assert client.post("/ask", json={"question": "x"}, headers=auth(t)).status_code == 401


def test_ask_rejects_denylisted_jti(client, monkeypatch):
    monkeypatch.setattr(slm, "jti_is_revoked", lambda jti: True)
    assert client.post("/ask", json={"question": "x"}, headers=auth(token())).status_code == 401


# --------------------------------------------------------------------------- happy path


def test_ask_returns_sql_and_rows(client, monkeypatch):
    monkeypatch.setattr(slm, "ollama_embed", lambda texts: [[0.1] * 1024])
    monkeypatch.setattr(slm, "qdrant_search",
                        lambda vector, top_k: [{"text": "Table nmc_complaints: complaints", "score": 0.9}])
    monkeypatch.setattr(slm, "ollama_generate",
                        lambda prompt: "SELECT ward FROM nmc_complaints LIMIT 1")
    seen = {}

    def fake_forward(sql, bearer):
        seen["sql"], seen["bearer"] = sql, bearer
        return 200, {"rows": [{"ward": "1"}], "row_count": 1, "role": "nmc_officer"}

    monkeypatch.setattr(slm, "query_forward", fake_forward)
    r = client.post("/ask", json={"question": "show me complaint wards"}, headers=auth(token()))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sql"] == "SELECT ward FROM nmc_complaints LIMIT 1"
    assert body["rows"] == [{"ward": "1"}]
    assert body["row_count"] == 1
    assert body["role"] == "nmc_officer"
    # RBAC inheritance: the CALLER's token is forwarded, not a service token
    assert seen["bearer"] == token()


def _capture_prompt(client, monkeypatch, contexts, response="SELECT 1"):
    captured = {}
    monkeypatch.setattr(slm, "ollama_embed", lambda texts: [[0.2] * 1024])
    monkeypatch.setattr(slm, "qdrant_search", lambda vector, top_k: contexts)
    monkeypatch.setattr(slm, "ollama_generate", lambda prompt: captured.update(prompt=prompt) or response)
    monkeypatch.setattr(slm, "query_forward", lambda sql, bearer: (200, {"rows": [], "row_count": 0, "role": "nmc_officer"}))
    client.post("/ask", json={"question": "HOW-MANY-COMPLAINTS"}, headers=auth(token()))
    return captured["prompt"]


def test_prompt_carries_context_rules_and_question(client, monkeypatch):
    p = _capture_prompt(client, monkeypatch, [{"text": "CTX-DOC", "table": None, "score": 0.8}])
    assert "CTX-DOC" in p                      # schema context injected (RAG)
    assert "HOW-MANY-COMPLAINTS" in p          # the question
    assert "SELECT" in p                       # SELECT-only rule
    assert "name, phone, email, address, aadhaar" in p  # PII denylist surfaced to the model


def test_prompt_labels_each_context_block_with_its_table(client, monkeypatch):
    """Gap 1: context blocks must carry a concrete table name so the model selects from
    named tables rather than guessing at unattributed prose."""
    p = _capture_prompt(client, monkeypatch, [
        {"text": "health camps run monthly", "table": "health_camp_records", "score": 0.9},
        {"text": "warehouse overview", "table": None, "score": 0.5},
    ])
    assert "[table: health_camp_records]" in p
    assert "[schema overview]" in p
    assert "[table: health_camp_records] health camps run monthly" in p


def test_prompt_enforces_table_selection_and_no_guess_sentinel(client, monkeypatch):
    """Gap 1: the prompt must (a) restrict the model to context tables, (b) forbid inventing
    a table, and (c) offer a sentinel so a vague question yields no guess."""
    p = _capture_prompt(client, monkeypatch, [{"text": "c", "table": "nmc_complaints", "score": 0.9}])
    assert "Choose exactly ONE table" in p
    assert "Never query a table that does not appear" in p
    assert "Restrict yourself to tables named in the schema context" in p
    assert "-- no relevant table" in p
    assert "Do not guess a table" in p


def test_context_table_sql_flows_through_gate_unchanged(client, monkeypatch):
    """A model that answers with the context table's SQL reaches query_forward verbatim
    (fences stripped by extract_sql) under the CALLER's token — the gate is untouched."""
    seen = {}
    monkeypatch.setattr(slm, "ollama_embed", lambda texts: [[0.4] * 1024])
    monkeypatch.setattr(slm, "qdrant_search", lambda vector, top_k: [
        {"text": "water sensor readings", "table": "water_sensor_readings", "score": 0.9}])
    monkeypatch.setattr(slm, "ollama_generate",
                        lambda prompt: "```sql\nSELECT count(*) FROM water_sensor_readings\n```")

    def fake_forward(sql, bearer):
        seen["sql"], seen["bearer"] = sql, bearer
        return 200, {"rows": [{"count": 3}], "row_count": 1, "role": "nmc_officer"}

    monkeypatch.setattr(slm, "query_forward", fake_forward)
    t = token()
    r = client.post("/ask", json={"question": "how many water readings"}, headers=auth(t))
    assert r.status_code == 200, r.text
    assert r.json()["sql"] == "SELECT count(*) FROM water_sensor_readings"
    assert seen["sql"] == "SELECT count(*) FROM water_sensor_readings"
    assert seen["bearer"] == t  # RBAC inheritance preserved


def test_generate_request_shape():
    """Charter parameters: qwen3:1.7b, temperature=0, think disabled, no streaming."""
    req = slm.build_generate_request("PROMPT")
    assert req["model"] == "qwen3:1.7b"
    assert req["prompt"] == "PROMPT"
    assert req["stream"] is False
    assert req["think"] is False
    assert req["options"]["temperature"] == 0


def test_retrieval_uses_expected_top_k(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(slm, "ollama_embed", lambda texts: [[0.3] * 1024])
    monkeypatch.setattr(slm, "qdrant_search", lambda vector, top_k: seen.update(k=top_k) or [])
    monkeypatch.setattr(slm, "ollama_generate", lambda prompt: "")
    monkeypatch.setattr(slm, "query_forward", lambda sql, bearer: (200, {"rows": [], "row_count": 0, "role": "x"}))
    client.post("/ask", json={"question": "q"}, headers=auth(token()))
    # Recall raised from 5 to 8 so the target table's docs stay in context (Gap 1).
    assert seen["k"] == 8
    assert seen["k"] == slm.TOP_K


# --------------------------------------------------------------------------- SQL extraction


def test_extract_plain():
    assert slm.extract_sql("SELECT 1") == "SELECT 1"


def test_extract_fenced_sql():
    assert slm.extract_sql("```sql\nSELECT 1\n```") == "SELECT 1"


def test_extract_fenced_bare():
    assert slm.extract_sql("```\nSELECT ward FROM t\n```") == "SELECT ward FROM t"


def test_extract_strips_think_blocks():
    assert slm.extract_sql("<think>reasoning here</think>\nSELECT 1") == "SELECT 1"


def test_extract_empty_raises():
    with pytest.raises(slm.NoSQLError):
        slm.extract_sql("   ")


# --------------------------------------------------------------------------- failure paths


def test_ask_model_produced_no_sql(client, monkeypatch):
    monkeypatch.setattr(slm, "ollama_embed", lambda texts: [[0.1] * 1024])
    monkeypatch.setattr(slm, "qdrant_search", lambda vector, top_k: [])
    monkeypatch.setattr(slm, "ollama_generate", lambda prompt: "  ")
    r = client.post("/ask", json={"question": "q"}, headers=auth(token()))
    assert r.status_code == 502
    assert "no sql" in r.json()["detail"].lower()


def test_ask_surfaces_gate_block(client, monkeypatch):
    """RBAC inheritance: queryService's 403 verdict passes through to the caller."""
    monkeypatch.setattr(slm, "ollama_embed", lambda texts: [[0.1] * 1024])
    monkeypatch.setattr(slm, "qdrant_search", lambda vector, top_k: [])
    monkeypatch.setattr(slm, "ollama_generate", lambda prompt: "SELECT * FROM health_camp_records")
    monkeypatch.setattr(slm, "query_forward",
                        lambda sql, bearer: (403, {"detail": {"reason": "table-rbac", "verdict": "blocked"}}))
    r = client.post("/ask", json={"question": "health records"}, headers=auth(token(role="nmc_officer")))
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "table-rbac"


def test_ask_admin_is_gated_by_query_not_by_slm(client, monkeypatch):
    """slmService does not duplicate the RBAC matrix; it forwards and surfaces the verdict."""
    monkeypatch.setattr(slm, "ollama_embed", lambda texts: [[0.1] * 1024])
    monkeypatch.setattr(slm, "qdrant_search", lambda vector, top_k: [])
    monkeypatch.setattr(slm, "ollama_generate", lambda prompt: "SELECT count(*) FROM nmc_complaints")
    monkeypatch.setattr(slm, "query_forward",
                        lambda sql, bearer: (403, {"detail": {"reason": "table-rbac", "verdict": "blocked"}}))
    r = client.post("/ask", json={"question": "complaints"}, headers=auth(token(role="admin")))
    assert r.status_code == 403


def test_ask_query_service_down(client, monkeypatch):
    """The gate's status passes through verbatim (403→403, 503→503): slm mirrors verdicts."""
    monkeypatch.setattr(slm, "ollama_embed", lambda texts: [[0.1] * 1024])
    monkeypatch.setattr(slm, "qdrant_search", lambda vector, top_k: [])
    monkeypatch.setattr(slm, "ollama_generate", lambda prompt: "SELECT 1")
    monkeypatch.setattr(slm, "query_forward", lambda sql, bearer: (503, {"detail": "database unreachable"}))
    r = client.post("/ask", json={"question": "q"}, headers=auth(token()))
    assert r.status_code == 503


def test_ask_retrieval_failure(client, monkeypatch):
    def boom(vector, top_k):
        raise RuntimeError("qdrant unreachable")

    monkeypatch.setattr(slm, "ollama_embed", lambda texts: [[0.1] * 1024])
    monkeypatch.setattr(slm, "qdrant_search", boom)
    r = client.post("/ask", json={"question": "q"}, headers=auth(token()))
    assert r.status_code == 503
