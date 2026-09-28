from fastapi import FastAPI, HTTPException, Depends, Request, Query
import os, jwt, json, httpx, asyncpg, urllib.parse
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from datetime import datetime, timezone
from aiokafka import AIOKafkaConsumer
load_dotenv()

app = FastAPI()

JAEGER_URL = os.getenv("JAEGER_URL")
QDRANT_URL = os.getenv("QDRANT_URL")
HTTP_INDEXER_URL = os.getenv("HTTP_INDEXER_URL", "http://schema-indexer:4005")
BOOTSTRAP_SERVERS = os.getenv("BOOTSTRAP_SERVERS", "kafka:29092")
DLQ_TOPIC = os.getenv("DLQ_TOPIC", "complaints.dlq.topic")

# SSRF allowlist — only internal Docker service hostnames are permitted
_URL_ALLOWLIST = {"jaeger", "qdrant"}

def _validate_url(name: str, url: str | None) -> bool:
    if not url:
        return True
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or ""
    if hostname not in _URL_ALLOWLIST:
        print(
            f"CRITICAL: {name}={url!r} hostname {hostname!r} not in allowlist "
            f"{_URL_ALLOWLIST}. Disabling integration.",
            flush=True,
        )
        return False
    return True

_jaeger_enabled = _validate_url("JAEGER_URL", JAEGER_URL)
_qdrant_enabled = _validate_url("QDRANT_URL", QDRANT_URL)

EXCLUDED_PATHS = ["/", "/docs", "/openapi.json", "/metrics"]

@app.middleware("http")
async def middle(request: Request, call_next):
    if request.url.path in EXCLUDED_PATHS:
        return await call_next(request)
    token = request.cookies.get("session_token")
    if not token:
        return JSONResponse(status_code=401, content={"detail": "no auth token found"})
    try:
        payl = jwt.decode(
            token,
            os.getenv("JWT_SECRET"),
            algorithms=["HS256"],
            issuer="nagar-auth",
            audience="nagar-services",
            options={"require": ["iss", "aud"]},
        )
    except jwt.ExpiredSignatureError:
        return JSONResponse(status_code=401, content={"detail": "token expired"})
    except jwt.InvalidTokenError:
        return JSONResponse(status_code=401, content={"detail": "invalid token"})
    role = payl.get("role")
    if role != "admin":
        return JSONResponse(status_code=403, content={"detail": "not allowed to view this page"})
    resp = await call_next(request)
    return resp

@app.get("/")
def chek():
    return {"status": "Running"}

@app.get("/health/cluster")
async def cluster_heal():
    status_report = {"postgres": "UNKNOWN", "qdrant": "UNKNOWN", "jaeger": "UNKNOWN"}
    async with httpx.AsyncClient() as client:
        if _qdrant_enabled and QDRANT_URL:
            try:
                res = await client.get(f"{QDRANT_URL}/healthz")
                status_report["qdrant"] = "UP" if res.status_code == 200 else "DOWN"
            except Exception:
                status_report["qdrant"] = "UNREACHABLE"
        else:
            status_report["qdrant"] = "DISABLED"

        if _jaeger_enabled and JAEGER_URL:
            try:
                res = await client.get(f"{JAEGER_URL}")
                status_report["jaeger"] = "UP" if res.status_code == 200 else "DOWN"
            except Exception:
                status_report["jaeger"] = "UNREACHABLE"
        else:
            status_report["jaeger"] = "DISABLED"

    return {"status": "evaluated", "components": status_report}

@app.get("/audit-logs")
async def get_audit(
    limit: int = Query(50, le=200),
    status_filter: str = Query(None, description="ALLOWED or BLOCKED"),
):
    conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
    try:
        if status_filter:
            query = "SELECT * FROM audit_logs WHERE status = $1 ORDER BY timestamp DESC LIMIT $2"
            rows = await conn.fetch(query, status_filter.upper(), limit)
        else:
            query = "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT $1"
            rows = await conn.fetch(query, limit)
        return {"count": len(rows), "logs": [dict(r) for r in rows]}
    finally:
        await conn.close()

@app.post("/vector/resync")
async def trigger():
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            resp = await client.post(f"{HTTP_INDEXER_URL}/reindex")
            resp.raise_for_status()
            body = resp.json()
            return {
                "status": "success",
                "message": "Schema re-indexing complete.",
                "chunks_indexed": body.get("chunks_indexed", 0),
            }
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Schema indexer is unreachable.")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Re-index failed: {str(exc)}")

@app.get("/dlq")
async def list_dlq(limit: int = Query(50, le=200)):
    messages = []
    consumer = AIOKafkaConsumer(
        DLQ_TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        auto_offset_reset="earliest",
        group_id=None,
    )
    await consumer.start()
    try:
        # Poll with a timeout instead of using an async iterator + consumer_timeout_ms;
        # getmany() returns empty batches when no records arrive, so the endpoint always
        # returns promptly even when the DLQ is empty.
        while len(messages) < limit:
            batch = await consumer.getmany(timeout_ms=3000, max_records=limit - len(messages))
            if not batch:
                break
            for _tp, msgs in batch.items():
                for msg in msgs:
                    try:
                        messages.append(json.loads(msg.value.decode("utf-8")))
                    except Exception:
                        messages.append({"raw": msg.value.decode("utf-8", errors="replace")})
    finally:
        await consumer.stop()
    return {"dlq_topic": DLQ_TOPIC, "count": len(messages), "items": messages}

@app.get("/traces/slow-queries")
async def get_slow(min_duration: int = 500):
    if not _jaeger_enabled:
        raise HTTPException(status_code=503, detail="Jaeger integration disabled")
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(
                f"{JAEGER_URL}/api/traces",
                params={"service": "query-service", "minDuration": f"{min_duration}ms", "limit": 20},
            )
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to query Jaeger trace engine: {str(e)}")
