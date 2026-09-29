# slmService — FastAPI NL→SQL (port 4004), Phase 7d fresh rebuild (ADR-013).
#
# CONTRACTS (verbatim — ARCHITECTURE §4.1 endpoint registry; §3.4 NL→SQL flow + guardrails;
# SECURITY §3: "The SLM path inherits all of the above because generated SQL must pass the
# same queryService gate before execution — the LLM has no direct database access";
# Phase-6 model contract: qwen3:1.7b + bge-m3 on the local Ollama; charter parameters
# temperature=0, "think": false):
#   GET  /         liveness (public)
#   GET  /health   ollama/qdrant/query status (public; 503 when any is down)
#   POST /ask      JWT; embed the question (bge-m3, /api/embed) -> RAG top-5 from qdrant
#                  nagar_schema -> prompt with schema context + SELECT-only + PII rules ->
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
TOP_K = 5
EMBED_DIM = 1024

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
        {"text": (hit.get("payload") or {}).get("text", ""), "score": hit.get("score", 0.0)}
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
Using ONLY the schema context below, write ONE PostgreSQL SELECT statement answering the
question.

Rules:
- Output ONLY the SQL, no prose, no markdown.
- Exactly one SELECT statement; never INSERT/UPDATE/DELETE/DDL.
- Never select these PII columns: name, phone, email, address, aadhaar.
- Restrict yourself to tables named in the schema context.

Schema context:
{context}

Question: {question}
SQL:"""


def build_prompt(question: str, contexts: list[dict]) -> str:
    ctx = "\n".join(f"- {c['text']}" for c in contexts if c.get("text"))
    return PROMPT_TEMPLATE.format(context=ctx or "(no schema context retrieved)", question=question)


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
    return sql.strip().rstrip(";").strip() or (raise_nosql())


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
        prompt = build_prompt(body.question, contexts)
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
