# slmService — FastAPI NL→SQL (port 4004), Phase 7d fresh rebuild (ADR-013).
#
# CONTRACTS (verbatim — ARCHITECTURE §4.1 endpoint registry; §3.4 NL→SQL flow + guardrails;
# SECURITY §3: "The SLM path inherits all of the above because generated SQL must pass the
# same queryService gate before execution — the LLM has no direct database access";
# Phase-6 model contract: qwen3:1.7b + bge-m3 on the local Ollama; charter parameters
# temperature=0, "think": false):
#   GET  /         liveness (public)
#   GET  /health   ollama/qdrant/query status (public; 503 when any is down)
#   POST /ask      JWT; embed the question (bge-m3, /api/embed) -> RAG top-k from qdrant
#                  nagar_schema (each block labeled with its table; the prompt must select a
#                  table present in context or emit the `-- no relevant table` sentinel) ->
#                  prompt with schema context + SELECT-only + PII rules ->
#                  qwen3:1.7b /api/generate (stream=false, think=false, temperature=0) ->
#                  extract the SQL (strips ```sql fences and <think> blocks) -> forward to
#                  queryService /query WITH THE CALLER'S BEARER TOKEN (RBAC inheritance:
#                  the LLM has no identity of its own) -> surface SQL + rows or the gate's
#                  verdict verbatim.
#
# Seams (module-level, monkeypatched in tests): ollama_embed, qdrant_search,
# ollama_generate, query_forward, jti_is_revoked, health_ollama, health_qdrant,
# health_query. Real implementations use httpx; every /ask path ends in an audit-worthy
# outcome at queryService (it audits), so this service does not duplicate the audit log.
import os
import re

import httpx
import jwt as pyjwt
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

ISSUER = "nagar-auth"
AUDIENCE = "nagar-services"
ALGORITHM = "HS256"
COOKIE_NAME = "session_token"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama.nagar-platform.svc.cluster.local:11434")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant.nagar-platform.svc.cluster.local:6333")
QUERY_URL = os.environ.get("QUERY_URL", "http://query-service.nagar-app.svc.cluster.local:4003")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")          # Phase 6: dim 1024, Cosine
GENERATE_MODEL = os.environ.get("GENERATE_MODEL", "qwen3:1.7b")  # Phase 6 payload
COLLECTION = os.environ.get("COLLECTION", "nagar_schema")
TOP_K = 8
EMBED_DIM = 1024

# Role-to-table allowlist (mirror of queryService ROLE_TABLES, CONVENTIONS §4 frozen).
# Defined here so the prompt can enumerate the caller's exact allowed set deterministically,
# complementing (not replacing) the queryService AST gate which enforces it at execution.
# These are the tables a role may SELECT through the NL path; if the matrix changes, both
# files must be updated together (the contract is frozen — I-6).
ROLE_ALLOWED_TABLES = {
    "nmc_officer": {
        "nmc_complaints", "traffic_events", "water_sensor_readings",
        "ev_bus_telemetry", "municipal_assets",
    },
    "ROLE_HEALTH_OFFICER": {
        "nmc_complaints", "traffic_events", "water_sensor_readings",
        "ev_bus_telemetry", "health_camp_records",
    },
}

app = FastAPI(title="slmService", docs_url=None, redoc_url=None, openapi_url=None)


class NoSQLError(Exception):
    pass


# --------------------------------------------------------------------------- seams


def ollama_embed(texts: list[str]) -> list[list[float]]:
    r = httpx.post(f"{OLLAMA_URL}/api/embed",
                   json={"model": EMBED_MODEL, "input": texts}, timeout=300)
    r.raise_for_status()
    out = r.json().get("embeddings") or []
    if len(out) != len(texts):
        raise RuntimeError(f"embed returned {len(out)} for {len(texts)} inputs")
    return out


def qdrant_search(vector: list[float], top_k: int) -> list[dict]:
    r = httpx.post(f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
                   json={"vector": vector, "limit": top_k, "with_payload": True}, timeout=60)
    r.raise_for_status()
    return [
        {
            "text": (hit.get("payload") or {}).get("text", ""),
            # Indexer payload carries the owning table (null for overview docs): surface it
            # so the prompt can label each context block with a concrete table name.
            "table": (hit.get("payload") or {}).get("table"),
            "score": hit.get("score", 0.0),
        }
        for hit in r.json().get("result", [])
    ]


def build_generate_request(prompt: str) -> dict:
    """Charter parameter block: qwen3:1.7b, deterministic, no thinking, no streaming."""
    return {
        "model": GENERATE_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }


def ollama_generate(prompt: str) -> str:
    r = httpx.post(f"{OLLAMA_URL}/api/generate", json=build_generate_request(prompt), timeout=600)
    r.raise_for_status()
    return r.json().get("response", "")


def query_forward(sql: str, bearer: str) -> tuple[int, dict]:
    """Forward generated SQL to the queryService gate with the CALLER's token."""
    r = httpx.post(f"{QUERY_URL}/query", json={"sql": sql},
                   headers={"Authorization": f"Bearer {bearer}"}, timeout=300)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"detail": r.text[:200]}


def jti_is_revoked(jti: str) -> bool:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sessions WHERE jti = %s AND revoked_at IS NOT NULL", (jti,))
        return cur.fetchone() is not None


def _conn():
    return psycopg_connect(os.environ["DATABASE_URL"], connect_timeout=5)


def psycopg_connect(*a, **kw):
    import psycopg

    return psycopg.connect(*a, **kw)


def _up(url: str, path: str) -> bool:
    try:
        return httpx.get(f"{url}{path}", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


def health_ollama() -> bool:
    return _up(OLLAMA_URL, "/api/tags")


def health_qdrant() -> bool:
    return _up(QDRANT_URL, "/healthz")


def health_query() -> bool:
    return _up(QUERY_URL, "/")


# --------------------------------------------------------------------------- prompt


PROMPT_TEMPLATE = """You are a SQL generator for a PostgreSQL civic-data warehouse.
Using the schema context AND the caller's explicit allowed-table set below, write ONE
PostgreSQL SELECT statement answering the question.

Rules:
- Output ONLY the SQL, no prose, no markdown.
- Exactly one SELECT statement; never INSERT/UPDATE/DELETE/DDL.
- Never reference these PII columns ANYWHERE (not even inside COUNT or WHERE):
  name, phone, email, address, aadhaar.
- For counts and totals use COUNT(event_id), never COUNT over a PII column.
- Choose exactly ONE table to query, and it MUST be one of the tables listed in the
  caller's allowed-table set (if one was provided). That set is authoritative: it is the
  complete list of tables this role may SELECT. The schema context below is for column-level
  detail only — it does not add or remove tables from the allowed set.
- If no table in the allowed set can answer the question, output exactly
  `-- no relevant table` and nothing else. Do not guess a table. Do not invent a table.
- Do not invent filter values that are not in the question; only filter on what is asked.

Schema context:
{context}

Question: {question}
SQL:"""


def _context_block(c: dict) -> str:
    """Label each retrieved block with its table so the model selects from named tables,
    not from unattributed prose (overview docs carry table=null)."""
    table = c.get("table")
    tag = f"[table: {table}]" if table else "[schema overview]"
    return f"- {tag} {c['text']}"


def build_prompt(question: str, contexts: list[dict], role: str | None = None) -> str:
    """Build the generation prompt. The caller's `role` is used to inject an explicit,
    deterministic table allowlist into the prompt so the small model does not have to
    infer the RBAC matrix from prose (Gap 2: prompt lacks a concrete table allowlist).
    The allowlist is a complement to the queryService AST gate, not a replacement."""
    ctx = "\n".join(_context_block(c) for c in contexts if c.get("text"))
    allowed = ROLE_ALLOWED_TABLES.get(role) if role else None
    allowed_clause = ""
    if allowed:
        allowed_clause = (
            "\nThe caller's role is `" + role + "`. The ONLY tables this role may SELECT are:\n"
            + " ".join(sorted(allowed)) + "\n"
            "You MUST choose a table from that set only. The schema context below is provided\n"
            "for column-level detail; it is NOT an additional table source — the allowed set above is\n"
            "authoritative. If no table in the allowed set can answer the question, output exactly\n"
            "`-- no relevant table` and nothing else."
        )
    return PROMPT_TEMPLATE.format(
        context=(ctx + allowed_clause) if ctx else "(no schema context retrieved)" + allowed_clause,
        question=question,
    )


FENCE_RE = re.compile(r"```(?:sql)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def extract_sql(response: str) -> str:
    """Pull the SQL out of the model output: drop <think> blocks, prefer a fenced block,
    fall back to the whole (stripped) text."""
    text = THINK_RE.sub("", response or "").strip()
    if not text:
        raise NoSQLError()
    m = FENCE_RE.search(text)
    sql = m.group(1).strip() if m else text
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise NoSQLError()
    return stripped


def raise_nosql():
    raise NoSQLError()


# --------------------------------------------------------------------------- auth


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"service misconfigured: {name} unset")
    return value


def claims_from_request(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing session")
    try:
        return pyjwt.decode(token, env("JWT_SECRET"), algorithms=[ALGORITHM],
                            audience=AUDIENCE, issuer=ISSUER)
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid or expired session")


def identity_from_request(request: Request) -> dict:
    claims = claims_from_request(request)
    if jti_is_revoked(claims["jti"]):
        raise HTTPException(status_code=401, detail="session revoked")
    return claims


# --------------------------------------------------------------------------- endpoints


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@app.get("/")
def liveness():
    return {"status": "ok", "service": "slmService"}


@app.get("/health")
def health():
    checks = {"ollama": health_ollama(), "qdrant": health_qdrant(), "query": health_query()}
    if not all(checks.values()):
        raise HTTPException(
            status_code=503,
            detail={k: ("ok" if v else "down") for k, v in checks.items()},
        )
    return {k: ("ok" if v else "down") for k, v in checks.items()}


@app.post("/ask")
def ask(body: AskBody, request: Request):
    claims = identity_from_request(request)
    bearer = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    try:
        vectors = ollama_embed([body.question])
        if len(vectors[0]) != EMBED_DIM:
            raise HTTPException(status_code=502, detail="embed dimension mismatch")
        contexts = qdrant_search(vectors[0], TOP_K)
        prompt = build_prompt(body.question, contexts, role=claims.get("role"))
        response = ollama_generate(prompt)
        sql = extract_sql(response)
    except NoSQLError:
        raise HTTPException(status_code=502, detail="model produced no SQL")
    except (httpx.HTTPError, RuntimeError):
        # Any retrieval/generation backend failure (connection, bad response shape) is a
        # readiness failure of a dependency, not a 500 with a leaked traceback.
        raise HTTPException(status_code=503, detail="retrieval or generation backend unreachable")

    status, payload = query_forward(sql, bearer)
    if status == 200:
        return {"sql": sql, "rows": payload.get("rows", []),
                "row_count": payload.get("row_count", 0), "role": payload.get("role", claims["role"])}
    detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    raise HTTPException(status_code=status, detail=detail)
