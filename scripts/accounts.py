"""Offline administrator CLI: no public registration, passwords never in argv."""
import argparse
import getpass
import sys

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.security import hash_password, username
from app.db.models import Account, Bookmark, LoginSession, ReadingProgress
from app.db.session import get_session_factory


def create_account(db, name, password, role="reader"):
    name = username(name)
    if role not in {"reader", "admin"}:
        raise ValueError("Unknown role")
    if db.scalar(select(Account.id).where(Account.username == name)):
        raise ValueError("Account already exists")
    account = Account(username=name, password_hash=hash_password(password), role=role)
    db.add(account)
    db.flush()
    return account


def revoke(db, account):
    db.execute(update(LoginSession).where(LoginSession.user_id == account.id).values(revoked=True))


def change_password(db, account, password):
    account.password_hash = hash_password(password)
    account.failed_attempts, account.locked_until = 0, None
    revoke(db, account)


def deactivate(db, account):
    if db.get_bind().dialect.name == "postgresql":
        # Serialize last-admin checks across concurrent operator CLI processes.
        db.execute(text("SELECT pg_advisory_xact_lock(791093442)"))
    admins = db.scalar(select(func.count()).select_from(Account).where(Account.role == "admin", Account.is_active))
    if account.role == "admin" and account.is_active and admins <= 1:
        raise ValueError("Cannot deactivate the last active administrator")
    account.is_active = False
    revoke(db, account)


def claim_local(db, account):
    """Explicit opt-in transfer; refuse conflicts, don't guess or merge ownership."""
    if not account.is_active:
        raise ValueError("Destination account is disabled")
    local_chapters = select(ReadingProgress.chapter_id).where(ReadingProgress.user_id == "local")
    if db.scalar(select(ReadingProgress.id).where(ReadingProgress.user_id == account.id,
                                                 ReadingProgress.chapter_id.in_(local_chapters)).limit(1)):
        raise ValueError("Destination already has conflicting progress; no records changed")
    counts = {}
    for model in (ReadingProgress, Bookmark):
        result = db.execute(update(model).where(model.user_id == "local").values(user_id=account.id))
        counts[model.__tablename__] = result.rowcount
    return counts


def read_password(from_stdin):
    if from_stdin:
        # Deliberate opt-in for secret-manager pipes; don't echo or save the input.
        value = sys.stdin.readline().rstrip("\r\n")
    else:
        if not sys.stdin.isatty():
            raise ValueError("Use an interactive terminal or explicit --password-stdin")
        value = getpass.getpass("New password (12–128 characters): ")
        if value != getpass.getpass("Repeat password: "):
            raise ValueError("Passwords do not match")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "password", "disable", "enable", "claim-local"])
    parser.add_argument("username")
    parser.add_argument("--role", choices=["admin", "reader"], default="reader")
    parser.add_argument("--password-stdin", action="store_true")
    parser.add_argument("--confirm-claim-local", action="store_true")
    args = parser.parse_args()
    try:
        name = username(args.username)
        password = read_password(args.password_stdin) if args.action in {"create", "password"} else None
        with get_session_factory()() as db:
            if args.action == "create":
                account = create_account(db, name, password, args.role)
            else:
                account = db.scalar(select(Account).where(Account.username == name).with_for_update())
                if not account:
                    raise ValueError("Account not found")
                if args.action == "password":
                    change_password(db, account, password)
                elif args.action == "disable":
                    deactivate(db, account)
                elif args.action == "enable":
                    account.is_active, account.failed_attempts, account.locked_until = True, 0, None
                elif args.action == "claim-local":
                    if not args.confirm_claim_local:
                        raise ValueError("Explicit --confirm-claim-local is required")
                    print(claim_local(db, account))
            db.commit()
        print("Account operation completed; no password/session token was printed.")
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")
    except SQLAlchemyError:
        parser.exit(1, "Database operation failed; check DB connectivity and migration.\n")


if __name__ == "__main__":
    main()
