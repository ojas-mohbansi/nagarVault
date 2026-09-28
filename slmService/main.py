import os
import re
import jwt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
load_dotenv()

from clients import ollama, qdrant, query
from schemas import AskRequest, AskResponse, HealthResponse

app = FastAPI()

JWT_SECRET = os.getenv("JWT_SECRET")
GENERATE_MODEL = "qwen3:1.7b"

EXCLUDED_PATHS = ["/", "/health", "/docs", "/openapi.json"]

SYSTEM_PROMPT_TEMPLATE = """\
You are a PostgreSQL expert for NagarVault, a civic data platform for Nagpur Municipal Corporation.
Your only job is to return a single valid PostgreSQL SELECT query that answers the user's question.

Rules you must follow without exception:
1. Return ONLY the SQL query. No explanation, no markdown, no code fences, no commentary.
2. The query MUST be a SELECT statement. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, or any other statement.
3. Never reference these columns, they are forbidden: name, phone, email, address, aadhaar.
4. The health_camp_records table requires role ROLE_HEALTH_OFFICER. Only generate queries for it if the user's role is ROLE_HEALTH_OFFICER.
5. Use PostgreSQL syntax. Use single quotes for string literals. Use NOW() for current timestamp. Use INTERVAL for date arithmetic.
6. If the question cannot be answered with a SQL SELECT query, return exactly: SELECT 'unsupported question' AS message;

Relevant schema context (use this to write accurate column and table names):
{schema_context}

User role: {role}
"""


@app.middleware("http")
async def middle(request: Request, call_next):
    if request.url.path in EXCLUDED_PATHS:
        return await call_next(request)
    token = request.headers.get("Authorization")
    if not token:
        return JSONResponse(status_code=401, content={"detail": "no auth token provided"})
    try:
        payl = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            issuer="nagar-auth",
            audience="nagar-services",
            options={"require": ["iss", "aud"]},
        )
    except jwt.ExpiredSignatureError:
        return JSONResponse(status_code=401, content={"detail": "token expired"})
    except jwt.InvalidTokenError:
        return JSONResponse(status_code=401, content={"detail": "invalid token"})
    request.state.username = payl.get("username")
    request.state.role = payl.get("role")
    request.state.user_id = payl.get("user_id")
    resp = await call_next(request)
    return resp


def strip_sql_fences(text: str) -> str:
    # Remove markdown code fences that LLMs commonly add
    text = re.sub(r"```sql\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```\s*", "", text)
    # Take only the first statement if the model returned multiple
    statements = [s.strip() for s in text.split(";") if s.strip()]
    if statements:
        return statements[0].rstrip(";").strip() + ";"
    return text.strip()


@app.get("/")
def chek():
    return {"status": "Running"}


@app.get("/health", response_model=HealthResponse)
async def health():
    ollama_status = await ollama.check_health()
    qdrant_status = await qdrant.check_health()
    query_status = await query.check_health()
    overall = "healthy" if all(s == "up" for s in [ollama_status, qdrant_status, query_status]) else "degraded"
    return HealthResponse(
        status=overall,
        ollama=ollama_status,
        qdrant=qdrant_status,
        query_service=query_status,
    )


@app.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, request: Request):
    role = request.state.role
    auth_token = request.headers.get("Authorization")

    print(f"[ask] question={body.question!r} department={body.department!r} role={role!r}")

    # Step 1: embed the question
    vector = await ollama.embed(body.question)

    # Step 2: retrieve relevant schema chunks from Qdrant
    chunks = await qdrant.search_schema(vector, top_k=5, department=body.department)
    if not chunks:
        raise HTTPException(
            status_code=503,
            detail="Schema index is empty. Run the schema indexer to populate Qdrant.",
        )

    # Step 3: build the system prompt with retrieved context
    schema_context = "\n\n".join(f"- {chunk}" for chunk in chunks)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema_context=schema_context, role=role)

    # Step 4: generate SQL via Qwen3:2b
    raw_sql = await ollama.generate_sql(system_prompt, body.question)
    sql = strip_sql_fences(raw_sql)

    print(f"[ask] generated_sql={sql!r}")

    # Step 5: execute via queryService (AST validation + RBAC happens there)
    result = await query.execute_sql(sql, auth_token)

    row_count = result.get("row_count", 0)
    data = result.get("data", [])

    print(f"[ask] row_count={row_count}")

    return AskResponse(
        question=body.question,
        sql=sql,
        row_count=row_count,
        data=data,
        schema_chunks_used=len(chunks),
        model=GENERATE_MODEL,
    )
