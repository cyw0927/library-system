"""One backup per invocation; persistent archives, no automatic deletion/upload."""
import argparse
import json
from pathlib import Path
import shutil
from uuid import uuid4

from app.core.config import get_settings
from app.core.security import utcnow
from scripts.backup import backup, sha256


def check_backups(directory, max_age_hours=26, min_free_mb=1024):
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ValueError("Backup directory is missing")
    if shutil.disk_usage(directory).free < min_free_mb * 1024 * 1024:
        raise ValueError("Insufficient free backup disk space")
    # Only this tool's completed pairs; timestamps/UUID names do not imply trust.
    completed = []
    for archive in directory.glob("library-*.dump"):
        manifest = Path(str(archive) + ".json")
        if archive.is_symlink() or manifest.is_symlink() or not manifest.is_file():
            continue
        completed.append((archive.stat().st_mtime, archive, manifest))
    if not completed:
        raise ValueError("No completed backup pair exists")
    modified, archive, manifest = max(completed, key=lambda entry: entry[0])
    if utcnow().timestamp() - modified > max_age_hours * 3600:
        raise ValueError("Latest backup is too old")
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if metadata.get("format") != "pg_dump_custom" or metadata.get("sha256") != sha256(archive):
        raise ValueError("Latest backup failed checksum verification")
    return archive


def create_backup(directory, pg_bin=None, min_free_mb=1024):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if shutil.disk_usage(directory).free < min_free_mb * 1024 * 1024:
        raise ValueError("Insufficient free backup disk space")
    name = "library-" + utcnow().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12] + ".dump"
    archive = backup(get_settings().database_url, directory / name, pg_bin)
    check_backups(directory, min_free_mb=min_free_mb)
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--pg-bin")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--max-age-hours", type=int, default=26)
    parser.add_argument("--min-free-mb", type=int, default=1024)
    args = parser.parse_args()
    if args.max_age_hours < 1 or args.min_free_mb < 1:
        parser.error("Age and free-space limits must be positive")
    try:
        if args.check_only:
            check_backups(args.directory, args.max_age_hours, args.min_free_mb)
            print("Latest backup: recent, checksum verified, disk space OK")
        else:
            archive = create_backup(args.directory, args.pg_bin, args.min_free_mb)
            print("Verified backup created:", archive.name)
    except Exception:
        parser.exit(1, "Backup job failed: check DB access, permissions, age/checksum and disk space; no existing backups were deleted.\n")


if __name__ == "__main__":
    main()
