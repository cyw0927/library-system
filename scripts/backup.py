"""Custom-format backups; restore ONLY into a different, explicitly empty DB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.security import utcnow


def pg_environment(database_url):
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg" or not url.database or not url.host:
        raise ValueError("Use an explicit PostgreSQL host and database")
    env = {**os.environ, "PGHOST": url.host, "PGPORT": str(url.port or 5432),
           "PGUSER": url.username or "postgres", "PGDATABASE": url.database,
           "PGPASSWORD": url.password or "", "PGCONNECT_TIMEOUT": "10"}
    # Do not let inherited libpq service settings redirect a backup/restore.
    for key in ("PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
        env.pop(key, None)
    if "sslmode" in url.query:
        env["PGSSLMODE"] = url.query["sslmode"]
    return env


def executable(name, pg_bin=None):
    path = Path(pg_bin) / (name + (".exe" if os.name == "nt" else "")) if pg_bin else shutil.which(name)
    if not path or not Path(path).is_file():
        raise ValueError(f"Install PostgreSQL 18 client tools or specify --pg-bin ({name} missing)")
    return str(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup(database_url, destination, pg_bin=None):
    path = Path(destination).resolve()
    manifest = Path(str(path) + ".json")
    if path.exists() or manifest.exists():
        raise ValueError("Backup/manifest already exists; choose a new path (never overwritten)")
    tool = executable("pg_dump", pg_bin)
    env = pg_environment(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL prevents races/symlink overwrites; restrict Unix permissions to owner.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            result = subprocess.run([tool, "--format=custom", "--no-owner", "--no-privileges",
                                     "--exclude-table-data=*.login_sessions"],
                                    stdout=output, stderr=subprocess.PIPE, env=env, timeout=3600)
        if result.returncode:
            raise ValueError("pg_dump failed; check client version, DB access and available disk space")
        metadata = dict(format="pg_dump_custom", created_at=utcnow().isoformat(),
                        sha256=sha256(path), sessions_excluded=True)
        with os.fdopen(os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
            json.dump(metadata, stream, indent=2)
    except BaseException:
        # Only our own newly created incomplete archive is removed, never an old backup.
        path.unlink(missing_ok=True)
        raise
    return path


def validate_restore_target(source_url, target_url):
    source, target = make_url(source_url), make_url(target_url)
    # Compare database name even across servers: conservative guard against accidental overwrite.
    if not target.database or target.database == source.database:
        raise ValueError("Restore database must have a different name from the source")
    pg_environment(target_url)
    engine = create_engine(target_url, connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as connection:
            count = connection.scalar(text("""SELECT count(*) FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
                AND c.relkind IN ('r','p','v','m','S','f')"""))
            if count:
                raise ValueError("Restore target is not empty; no objects were changed")
    finally:
        engine.dispose()


def restore(source_url, target_url, archive, pg_bin=None, confirmed=False):
    if not confirmed:
        raise ValueError("Explicit --confirm-empty-restore is required")
    path = Path(archive).resolve()
    manifest = Path(str(path) + ".json")
    if not path.is_file() or not manifest.is_file():
        raise ValueError("Archive and checksum manifest are both required")
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if metadata.get("sha256") != sha256(path) or metadata.get("format") != "pg_dump_custom":
        raise ValueError("Backup checksum/format mismatch; restore refused")
    tool = executable("pg_restore", pg_bin)
    validate_restore_target(source_url, target_url)
    env = pg_environment(target_url)
    # --dbname uses only the database NAME; password never appears in process argv.
    result = subprocess.run([tool, "--dbname", env["PGDATABASE"], "--single-transaction",
                             "--exit-on-error", "--no-owner", "--no-privileges", str(path)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=3600)
    if result.returncode:
        raise ValueError("pg_restore failed and rolled back; check client version, extensions and privileges")
    engine = create_engine(target_url)
    try:
        with engine.begin() as connection:
            # Pre-login MVP backups have no session table; migrate AFTER restore.
            if inspect(connection).has_table("login_sessions"):
                connection.execute(text("UPDATE login_sessions SET revoked = true"))
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "restore"])
    parser.add_argument("path", help="New archive path, or trusted archive to restore")
    parser.add_argument("--pg-bin")
    parser.add_argument("--confirm-empty-restore", action="store_true")
    args = parser.parse_args()
    try:
        source_url = get_settings().database_url
        if args.action == "create":
            print("Backup created:", backup(source_url, args.path, args.pg_bin))
        else:
            target_url = os.getenv("RESTORE_DATABASE_URL", "")
            if not target_url:
                raise ValueError("Set RESTORE_DATABASE_URL to a NEW empty database")
            restore(source_url, target_url, args.path, args.pg_bin, args.confirm_empty_restore)
            print("Restore completed into the separate empty database; sessions are invalidated.")
    except (ValueError, OSError, SQLAlchemyError, subprocess.TimeoutExpired):
        # Never print raw driver errors/URLs; keep credentials and query text private.
        parser.exit(1, "Backup/restore refused or failed. Check path/checksum, separate empty target, DB access and client tools.\n")


if __name__ == "__main__":
    main()
