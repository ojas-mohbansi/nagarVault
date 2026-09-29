# seed_admin.py — first-admin bootstrap ritual (OPERATIONS §5; sanctioned §9.1).
#
# The first admin cannot be created through POST /create (it requires an admin JWT), so
# the operator seeds it out-of-band from inside the pod. Generates a strong password and
# prints it ONCE (record it in the operator vault; never git — I-3). Re-running is a
# no-op if the user exists.
#
# Usage (from OPERATIONS §5):
#   kubectl -n nagar-app exec deploy/auth-service -- \
#     python seed_admin.py --username admin --user-id admin-001
import argparse
import secrets
import sys

import psycopg

import app as auth


def fetch_user(username: str) -> dict | None:
    return auth.fetch_user(username)


def insert_user(user_id: str, username: str, password_hash: str, role: str) -> None:
    auth.insert_user(user_id, username, password_hash, role)


def seed(username: str, user_id: str, password: str | None, connect=None) -> str | None:
    """Idempotent seed. Returns the generated password, or None if user exists.
    `connect` is an injection seam for the hermetic tests; production uses DATABASE_URL."""
    existing = fetch_user(username)
    if existing is not None:
        return None

    generated = password or (secrets.token_urlsafe(18) + "!Aa1")
    insert_user(user_id, username, auth.hash_password(generated), "admin")
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the first admin user (idempotent).")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--user-id", default="admin-001")
    parser.add_argument("--password", default=None,
                        help="optional explicit password; omit to generate one")
    args = parser.parse_args()

    pw = seed(args.username, args.user_id, args.password,
              connect=lambda: psycopg.connect(auth.env("DATABASE_URL"), connect_timeout=5))
    if pw is None:
        print(f"user '{args.username}' already exists — no-op")
        return 0
    print("ADMIN PASSWORD (record in the operator vault; shown once):")
    print(pw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
