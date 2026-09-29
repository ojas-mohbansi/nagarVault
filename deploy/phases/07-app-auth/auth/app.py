# authService — FastAPI auth API (port 4000), Phase 7a fresh rebuild (ADR-013).
#
# CONTRACTS (verbatim, no drift — ARCHITECTURE §4.1 endpoint registry, SECURITY §2
# identity chain, CONVENTIONS §4 port registry, Phase-5 DDL users/sessions):
#   GET  /         liveness (public)
#   GET  /dbcheck  SELECT 1 against nagardb (public)
#   POST /login    argon2id verify against users; HS256 JWT with claims
#                  iss=nagar-auth, aud=nagar-services, jti, sub, role, exp (60 min);
#                  session_token cookie (httponly, samesite=lax, secure per env);
#                  sessions row for revocation; 5 req/min/IP -> 429
#   GET  /whoami   cookie/Bearer identity echo; denylisted jti -> 401
#   POST /create   admin-JWT-gated user creation
#   POST /logout   records jti revocation (idempotent)
#
# The database access surface is the module-level function seam below (fetch_user,
# insert_session, jti_is_revoked, revoke_session, insert_user, dbcheck_query): tests
# monkeypatch these; the real implementations use psycopg3 against DATABASE_URL.
# Env is read per-request (JWT_SECRET, COOKIE_SECURE, DATABASE_URL), never at import,
# so the hermetic suite can set env per test.
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Literal

import jwt as pyjwt
import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

ISSUER = "nagar-auth"
AUDIENCE = "nagar-services"
TOKEN_TTL_S = 3600  # 60-minute TTL (SECURITY §2)
ALGORITHM = "HS256"
COOKIE_NAME = "session_token"
LOGIN_RATE_LIMIT = 5  # per 60s per client IP (SECURITY §2)
RATE_WINDOW_S = 60

ph = PasswordHasher()  # argon2id (SECURITY §2)

app = FastAPI(title="authService", docs_url=None, redoc_url=None, openapi_url=None)

# Dummy hash used to burn verify time for unknown users (no user enumeration).
_DUMMY_HASH = ph.hash("timing-equalizer-not-a-credential")


# --------------------------------------------------------------------------- seams


def fetch_user(username: str) -> dict | None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, username, password_hash, role, is_active FROM users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "user_id": row[0],
        "username": row[1],
        "password_hash": row[2],
        "role": row[3],
        "is_active": row[4],
    }


def insert_session(jti: str, user_id: str, expires_at_epoch: int) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sessions (jti, user_id, issued_at, expires_at) VALUES (%s, %s, now(), %s)",
            (jti, user_id, datetime.fromtimestamp(expires_at_epoch, tz=timezone.utc)),
        )
        conn.commit()


def jti_is_revoked(jti: str) -> bool:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sessions WHERE jti = %s AND revoked_at IS NOT NULL", (jti,)
        )
        return cur.fetchone() is not None


def revoke_session(jti: str) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE sessions SET revoked_at = now() WHERE jti = %s AND revoked_at IS NULL",
            (jti,),
        )
        conn.commit()


def insert_user(user_id: str, username: str, password_hash: str, role: str) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, username, password_hash, role) VALUES (%s, %s, %s, %s)",
            (user_id, username, password_hash, role),
        )
        conn.commit()


def dbcheck_query() -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()


def _conn():
    return psycopg.connect(env("DATABASE_URL"), connect_timeout=5)


# --------------------------------------------------------------------------- helpers


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"service misconfigured: {name} unset")
    return value


def jwt_secret() -> str:
    return env("JWT_SECRET")


def cookie_secure() -> bool:
    # Mandatory true once edge TLS is live (Phase 8, SECURITY §2); cluster-internal
    # E2E on the disposable substrate runs with it false until then.
    return os.environ.get("COOKIE_SECURE", "false").lower() == "true"


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def issue_token(user: dict) -> tuple[str, str, int]:
    now = int(time.time())
    jti = uuid.uuid4().hex
    token = pyjwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": user["user_id"],
            "role": user["role"],
            "jti": jti,
            "iat": now,
            "exp": now + TOKEN_TTL_S,
        },
        jwt_secret(),
        algorithm=ALGORITHM,
    )
    return token, jti, now + TOKEN_TTL_S


def decode_token(token: str) -> dict:
    try:
        return pyjwt.decode(
            token, jwt_secret(), algorithms=[ALGORITHM], audience=AUDIENCE, issuer=ISSUER
        )
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid or expired session")


def claims_from_request(request: Request) -> dict:
    """Decode cookie/Bearer token to claims. 401 on absent/garbage/expired tokens.
    Does NOT consult the revocation list (logout must stay idempotent — a second
    logout of an already-revoked session is still a valid 200)."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing session")
    return decode_token(token)


def identity_from_request(request: Request) -> dict:
    claims = claims_from_request(request)
    if jti_is_revoked(claims["jti"]):
        raise HTTPException(status_code=401, detail="session revoked")
    return claims


def admin_identity(claims: dict = Depends(identity_from_request)) -> dict:
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return claims


# --------------------------------------------------------------------------- rate limit

_attempts: dict[str, deque] = defaultdict(deque)


def reset_rate_limiter() -> None:
    _attempts.clear()


def login_allowed(ip: str) -> bool:
    now = time.time()
    seen = _attempts[ip]
    while seen and seen[0] <= now - RATE_WINDOW_S:
        seen.popleft()
    if len(seen) >= LOGIN_RATE_LIMIT:
        return False
    seen.append(now)
    return True


# --------------------------------------------------------------------------- schemas


class Credentials(BaseModel):
    username: str
    password: str


class NewUser(BaseModel):
    username: str
    password: str
    role: Literal["nmc_officer", "ROLE_HEALTH_OFFICER", "admin"]


# --------------------------------------------------------------------------- endpoints


@app.get("/")
def liveness():
    return {"status": "ok", "service": "authService"}


@app.get("/dbcheck")
def dbcheck():
    try:
        dbcheck_query()
    except Exception:  # noqa: BLE001 - any DB failure means not ready
        raise HTTPException(status_code=503, detail="database unreachable")
    return {"status": "ok"}


@app.post("/login")
def login(body: Credentials, request: Request, response: Response):
    client_ip = request.client.host if request.client else "unknown"
    if not login_allowed(client_ip):
        raise HTTPException(status_code=429, detail="login rate limit exceeded")

    user = fetch_user(body.username)
    password_hash = user["password_hash"] if user else _DUMMY_HASH
    ok = verify_password(body.password, password_hash) and bool(user and user["is_active"])
    if not ok:
        raise HTTPException(status_code=401, detail="invalid credentials")

    token, jti, expires_at = issue_token(user)
    insert_session(jti, user["user_id"], expires_at)
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        max_age=TOKEN_TTL_S,
        path="/",
    )
    return {"status": "ok", "role": user["role"]}


@app.get("/whoami")
def whoami(claims: dict = Depends(identity_from_request)):
    return {"sub": claims["sub"], "role": claims["role"], "jti": claims["jti"], "exp": claims["exp"]}


@app.post("/create")
def create(body: NewUser, admin: dict = Depends(admin_identity)):
    if fetch_user(body.username) is not None:
        raise HTTPException(status_code=409, detail="username already exists")
    user_id = f"{body.username}-{uuid.uuid4().hex[:8]}"
    insert_user(user_id, body.username, hash_password(body.password), body.role)
    return {"status": "ok", "user_id": user_id, "username": body.username, "role": body.role}


@app.post("/logout")
def logout(request: Request, response: Response):
    claims = claims_from_request(request)  # 401 when absent/invalid; revoked stays OK
    revoke_session(claims["jti"])  # idempotent: WHERE revoked_at IS NULL
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "ok"}
