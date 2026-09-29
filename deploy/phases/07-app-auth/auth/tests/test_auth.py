# authService test suite — Phase 7a (hermetic; no database, no network).
#
# CONTRACT UNDER TEST (ARCHITECTURE §4.1 endpoint registry, SECURITY §2 identity chain,
# Phase-5 DDL users/sessions tables):
#   GET  /         liveness, public
#   GET  /dbcheck  SELECT 1, public
#   POST /login    argon2id verify; HS256 JWT iss=nagar-auth aud=nagar-services,
#                  jti/sub/role/exp(60min); session_token cookie httponly samesite=lax
#                  (secure per COOKIE_SECURE); sessions row; 5 req/min/IP -> 429
#   GET  /whoami   cookie or Bearer identity echo; denylisted jti rejected
#   POST /create   admin-JWT-gated user creation; unknown role rejected; duplicate 409
#   POST /logout   revokes jti (idempotent); subsequent /whoami 401
#
# The DB seam is the module-level function surface of app.py (fetch_user, insert_session,
# revoke_session, jti_is_revoked, insert_user, dbcheck_query); tests monkeypatch it, so the
# suite runs anywhere python+pytest runs. The REAL database path is proven by the in-cluster
# E2E gate (mission log G7a.6), not here.
import sys
import time
from pathlib import Path

import pytest
import jwt as pyjwt
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as auth  # noqa: E402

TEST_JWT_SECRET = "test-secret-not-a-real-credential"
ALG = "HS256"
ADMIN = "admin"
OFFICER = "nmc_officer"


class FakeDB:
    """In-memory stand-in for the users/sessions tables (Phase-5 DDL shapes)."""

    def __init__(self):
        self.users = {}
        self.sessions = {}

    def add_user(self, user_id, username, password_hash, role):
        self.users[username] = {
            "user_id": user_id,
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "is_active": True,
        }


@pytest.fixture()
def db():
    return FakeDB()


@pytest.fixture()
def client(db, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setattr(auth, "fetch_user", lambda username: db.users.get(username))
    monkeypatch.setattr(
        auth,
        "insert_session",
        lambda jti, user_id, expires_at: db.sessions.setdefault(
            jti, {"user_id": user_id, "expires_at": expires_at, "revoked_at": None}
        ),
    )
    monkeypatch.setattr(
        auth,
        "jti_is_revoked",
        lambda jti: jti not in db.sessions or db.sessions[jti]["revoked_at"] is not None,
    )
    monkeypatch.setattr(
        auth,
        "revoke_session",
        lambda jti: db.sessions[jti].update(revoked_at=time.time()) if jti in db.sessions else None,
    )
    monkeypatch.setattr(
        auth,
        "insert_user",
        lambda user_id, username, password_hash, role: db.users.setdefault(
            username,
            {"user_id": user_id, "username": username, "password_hash": password_hash, "role": role, "is_active": True},
        )
        or (None if username in db.users else None),
    )
    auth.reset_rate_limiter()
    with TestClient(auth.app) as c:
        yield c


def seed(db, username=ADMIN, role=ADMIN, password="Correct-Horse-1"):
    db.add_user("admin-001" if role == ADMIN else "officer-001", username, auth.hash_password(password), role)
    return password


# --------------------------------------------------------------------------- liveness


def test_root_liveness(client):
    r = client.get("/")
    assert r.status_code == 200


def test_dbcheck_ok(client, monkeypatch):
    monkeypatch.setattr(auth, "dbcheck_query", lambda: None)
    assert client.get("/dbcheck").status_code == 200


def test_dbcheck_fails_without_db(client, monkeypatch):
    def boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(auth, "dbcheck_query", boom)
    assert client.get("/dbcheck").status_code == 503


# --------------------------------------------------------------------------- login


def test_login_success_sets_cookie_and_valid_jwt(client, db):
    password = seed(db)
    r = client.post("/login", json={"username": ADMIN, "password": password})
    assert r.status_code == 200, r.text
    set_cookie = r.headers["set-cookie"]
    assert "session_token=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    assert "secure" not in set_cookie.lower()  # COOKIE_SECURE=false pre-Phase-8

    token = client.cookies["session_token"]
    claims = pyjwt.decode(token, TEST_JWT_SECRET, algorithms=[ALG], audience="nagar-services")
    assert claims["iss"] == "nagar-auth"
    assert claims["sub"] == "admin-001"
    assert claims["role"] == ADMIN
    assert claims["exp"] - claims["iat"] == 3600  # 60-minute TTL, SECURITY §2
    assert claims["jti"]
    # sessions row recorded
    assert claims["jti"] in db.sessions


def test_login_cookie_secure_flag(client, db, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "true")
    password = seed(db)
    r = client.post("/login", json={"username": ADMIN, "password": password})
    assert "secure" in r.headers["set-cookie"].lower()


def test_login_wrong_password_401(client, db):
    seed(db, password="Correct-Horse-1")
    r = client.post("/login", json={"username": ADMIN, "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_user_401(client, db):
    r = client.post("/login", json={"username": "ghost", "password": "x"})
    assert r.status_code == 401


def test_login_rate_limit_429_on_sixth_attempt(client, db):
    seed(db, password="Correct-Horse-1")
    for _ in range(5):
        assert client.post("/login", json={"username": ADMIN, "password": "wrong"}).status_code == 401
    r6 = client.post("/login", json={"username": ADMIN, "password": "Correct-Horse-1"})
    assert r6.status_code == 429  # counted per attempt, not per success (SECURITY §2)


# --------------------------------------------------------------------------- whoami


def test_whoami_echoes_identity(client, db):
    password = seed(db)
    client.post("/login", json={"username": ADMIN, "password": password})
    r = client.get("/whoami")
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == ADMIN
    assert body["sub"] == "admin-001"


def test_whoami_rejects_missing_token(client):
    assert client.get("/whoami").status_code == 401


def test_whoami_rejects_garbage_token(client):
    r = client.get("/whoami", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_whoami_rejects_wrong_audience(client):
    token = pyjwt.encode(
        {"iss": "nagar-auth", "aud": "somewhere-else", "sub": "x", "role": ADMIN,
         "jti": "j", "iat": int(time.time()), "exp": int(time.time()) + 60},
        TEST_JWT_SECRET, algorithm=ALG,
    )
    r = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_whoami_rejects_denylisted_jti(client, db):
    password = seed(db)
    client.post("/login", json={"username": ADMIN, "password": password})
    jti = pyjwt.decode(client.cookies["session_token"], TEST_JWT_SECRET, algorithms=[ALG],
                       audience="nagar-services")["jti"]
    db.sessions[jti]["revoked_at"] = time.time()
    assert client.get("/whoami").status_code == 401


# --------------------------------------------------------------------------- create


def test_create_requires_admin(client, db):
    officer_pw = seed(db, username="officer", role=OFFICER, password="Officer-Pw-1")
    client.post("/login", json={"username": "officer", "password": officer_pw})
    r = client.post("/create", json={"username": "newbie", "role": OFFICER, "password": "Newbie-Pw-1"})
    assert r.status_code == 403


def test_create_requires_auth_at_all(client, db):
    r = client.post("/create", json={"username": "newbie", "role": OFFICER, "password": "Newbie-Pw-1"})
    assert r.status_code == 401


def test_create_as_admin_succeeds_and_hashes(client, db):
    admin_pw = seed(db)
    client.post("/login", json={"username": ADMIN, "password": admin_pw})
    r = client.post("/create", json={"username": "newbie", "role": OFFICER, "password": "Newbie-Pw-1"})
    assert r.status_code == 200, r.text
    assert db.users["newbie"]["role"] == OFFICER
    assert db.users["newbie"]["password_hash"].startswith("$argon2id$")
    assert "Newbie-Pw-1" not in db.users["newbie"]["password_hash"]


def test_create_rejects_unknown_role(client, db):
    admin_pw = seed(db)
    client.post("/login", json={"username": ADMIN, "password": admin_pw})
    r = client.post("/create", json={"username": "sneaky", "role": "superadmin", "password": "Sneaky-Pw-1"})
    assert r.status_code == 422


def test_create_duplicate_username_409(client, db):
    admin_pw = seed(db)
    client.post("/login", json={"username": ADMIN, "password": admin_pw})
    r = client.post("/create", json={"username": ADMIN, "role": OFFICER, "password": "Whatever-1"})
    assert r.status_code == 409


# --------------------------------------------------------------------------- logout


def test_logout_revokes_session(client, db):
    password = seed(db)
    client.post("/login", json={"username": ADMIN, "password": password})
    assert client.get("/whoami").status_code == 200
    r = client.post("/logout")
    assert r.status_code == 200
    assert client.get("/whoami").status_code == 401  # jti denylisted (SECURITY §2)


def test_logout_idempotent(client, db):
    password = seed(db)
    client.post("/login", json={"username": ADMIN, "password": password})
    token = client.cookies["session_token"]
    assert client.post("/logout").status_code == 200
    # First logout also cleared the cookie jar, so a bare second call is 401 (no session).
    assert client.post("/logout").status_code == 401
    # Presenting the SAME (now-revoked) token is still a 200 no-op — logout is idempotent
    # and revocation state never errors the path (SECURITY §2 jti denylist).
    r = client.post("/logout", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


# --------------------------------------------------------------------------- seed_admin


def test_seed_admin_generates_password_once(db, monkeypatch):
    import seed_admin

    monkeypatch.setattr(seed_admin, "fetch_user", lambda username: db.users.get(username))
    monkeypatch.setattr(
        seed_admin, "insert_user",
        lambda user_id, username, password_hash, role: db.users.update(
            {username: {"user_id": user_id, "username": username, "password_hash": password_hash,
                        "role": role, "is_active": True}}),
    )
    pw1 = seed_admin.seed("admin", "admin-001", None, connect=lambda: None)
    assert pw1 and db.users["admin"]["password_hash"].startswith("$argon2id$")
    pw2 = seed_admin.seed("admin", "admin-001", None, connect=lambda: None)
    assert pw2 is None  # re-run is a no-op (OPERATIONS §5)
    assert auth.verify_password(pw1, db.users["admin"]["password_hash"])


def test_seed_admin_explicit_password(db, monkeypatch):
    import seed_admin

    monkeypatch.setattr(seed_admin, "fetch_user", lambda username: db.users.get(username))
    monkeypatch.setattr(
        seed_admin, "insert_user",
        lambda user_id, username, password_hash, role: db.users.update(
            {username: {"user_id": user_id, "username": username, "password_hash": password_hash,
                        "role": role, "is_active": True}}),
    )
    pw = seed_admin.seed("admin", "admin-001", "Given-Pw-123", connect=lambda: None)
    assert pw == "Given-Pw-123"
