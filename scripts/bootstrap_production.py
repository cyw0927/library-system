"""One-off owner-only migration/extension bootstrap and least-privilege runtime grants."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from psycopg import Error as PsycopgError, sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings


def main():
    settings = get_settings()
    if settings.app_env != "production":
        raise SystemExit("This owner-only bootstrap requires APP_ENV=production")
    password = Path("/run/secrets/runtime_password").read_text(encoding="utf-8").strip()
    if len(password) < 16:
        raise SystemExit("Use a random runtime DB password of at least 16 characters")
    url = make_url(settings.database_url)
    if url.username == "library_runtime":
        raise SystemExit("Bootstrap requires a separate database-owner credential")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            cursor = connection.connection.driver_connection.cursor()
            try:
                exists = connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname='library_runtime'"))
                if not exists:
                    cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION").format(sql.Identifier("library_runtime")))
                memberships = connection.scalar(text("SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='library_runtime')"))
                if memberships:
                    raise SystemExit("Runtime role has existing role memberships; refuse possible privilege escalation")
                # The plaintext password never becomes SQL/log text, only a SCRAM verifier.
                verifier = connection.connection.driver_connection.pgconn.encrypt_password(
                    password.encode(), b"library_runtime", algorithm=b"scram-sha-256").decode()
                cursor.execute(sql.SQL("ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD {}").format(sql.Identifier("library_runtime"), sql.Literal(verifier)))
                cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(url.database), sql.Identifier("library_runtime")))
                cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                cursor.execute("REVOKE CREATE ON SCHEMA public FROM library_runtime")
                cursor.execute(sql.SQL("REVOKE CREATE ON DATABASE {} FROM library_runtime").format(sql.Identifier(url.database)))
                cursor.execute("GRANT USAGE ON SCHEMA public TO library_runtime")
                cursor.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO library_runtime")
                cursor.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO library_runtime")
                cursor.execute("REVOKE INSERT, UPDATE, DELETE ON public.alembic_version FROM library_runtime")
                cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO library_runtime").format(sql.Identifier(url.username)))
                cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO library_runtime").format(sql.Identifier(url.username)))
            finally:
                cursor.close()
        print("Owner bootstrap complete: pgvector + migrations; runtime has DML only, no DDL/superuser.")
    except (SQLAlchemyError, PsycopgError):
        raise SystemExit("Bootstrap failed; check owner privilege, extension availability and secret configuration") from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
