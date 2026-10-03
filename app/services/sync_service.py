import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import PurePosixPath
from threading import Lock

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.db.models import Book, Chapter, Paragraph, SourceDocument, SyncRun, SyncState, Volume
from app.services.github_client import GitHubClient, GitHubError, Snapshot
from app.services.metadata_service import is_readme, map_path, natural_key, readable, readme_metadata, slug
from app.services.parser_service import ParseError, parse_chapter

_local_lock = Lock()


class SyncBusy(RuntimeError):
    pass


@contextmanager
def sync_lock(engine, repository):
    if not _local_lock.acquire(blocking=False):
        raise SyncBusy("A sync is already running")
    key = int.from_bytes(hashlib.sha256(repository.encode()).digest()[:8], "big", signed=True)
    try:
        with engine.connect() as connection:
            locked = False
            try:
                if engine.dialect.name == "postgresql":
                    locked = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
                    if not locked:
                        raise SyncBusy("A sync is already running")
                yield
            finally:
                if locked:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    finally:
        _local_lock.release()


def sync_snapshot(session: Session, source: GitHubClient, snapshot: Snapshot) -> dict:
    report = dict(commit=snapshot.commit, scanned=len(snapshot.files), created=0, updated=0,
                  unchanged=0, deactivated=0, errors=[])
    run = SyncRun(source_commit=snapshot.commit)
    session.add(run)
    session.commit()
    states = {x.github_path: x for x in session.scalars(select(SyncState))}
    docs = {x.github_path: x for x in session.scalars(select(SourceDocument))}
    books = {x.github_path: x for x in session.scalars(select(Book))}
    volumes = {x.github_path: x for x in session.scalars(select(Volume))}
    paths = {f.path for f in snapshot.files}
    chapter_paths = sorted((p for p in paths if not is_readme(p) and "/" in p), key=natural_key)
    ordering = {p: n for n, p in enumerate(chapter_paths)}

    def parent(path):
        mapped = map_path(path)
        root = mapped.book_path
        doc = docs.get(f"{root}/README.md")
        info = doc.metadata_json if doc and doc.is_active else readme_metadata("", root)
        book = books.get(root)
        if book is None:
            book = Book(slug=slug(root), github_path=root, title=info["title"])
            session.add(book)
            books[root] = book
        for key in ("title", "original_title", "author", "description", "status"):
            setattr(book, key, info[key])
        book.is_active = True
        session.flush()
        volume = None
        if mapped.volume_path:
            vp = mapped.volume_path
            vd = docs.get(f"{vp}/README.md")
            vi = vd.metadata_json if vd and vd.is_active else readme_metadata("", vp.split("/")[-1])
            volume = volumes.get(vp)
            # The directory prefix, not the chapter filename, provides volume numbering.
            import re
            match = re.match(r"(\d+)_", vp.split("/")[-1])
            number = int(match[1]) if match and int(match[1]) > 0 else None
            if volume is None:
                volume = Volume(book=book, github_path=vp, slug=slug(vp.split("/")[-1]), title=vi["title"])
                session.add(volume)
                volumes[vp] = volume
            volume.title, volume.original_title = vi["title"], vi["original_title"]
            volume.volume_number, volume.sort_order, volume.is_active = number, number or 0, True
            book.book_type = "series"
            session.flush()
        return mapped, book, volume

    # Fetch README first; every file has an independent transaction.
    ordered = sorted(snapshot.files, key=lambda f: (not is_readme(f.path), natural_key(f.path)))
    for file in ordered:
        state = states.get(file.path)
        if state and state.github_sha == file.sha and state.sync_status == "synced":
            if state.entity_type == "chapter":
                session.execute(update(Chapter).where(Chapter.id == state.entity_id).values(source_commit=snapshot.commit))
            report["unchanged"] += 1
            continue
        created = state is None or state.entity_id is None
        try:
            content = source.content(file, snapshot.commit)
            if is_readme(file.path) or "/" not in file.path:
                entity = docs.get(file.path)
                if entity is None:
                    entity = SourceDocument(github_path=file.path)
                    session.add(entity)
                    docs[file.path] = entity
                entity.github_sha, entity.source_commit = file.sha, snapshot.commit
                entity.markdown_content = content
                entity.metadata_json = readme_metadata(content, PurePosixPath(file.path).parent.name)
                entity.is_active = True
                kind = "metadata"
            else:
                parsed = parse_chapter(content)
                mapped, book, volume = parent(file.path)
                entity = session.scalar(select(Chapter).where(Chapter.github_path == file.path))
                if entity is None:
                    entity = Chapter(github_path=file.path, book=book, volume=volume)
                    session.add(entity)
                entity.book, entity.volume = book, volume
                entity.title = parsed.title or readable(mapped.code)
                entity.chapter_number, entity.chapter_code, entity.pov = mapped.number, mapped.code, mapped.pov
                entity.github_sha, entity.markdown_content = file.sha, content
                entity.source_commit = snapshot.commit
                entity.sort_order, entity.is_active = ordering[file.path], True
                # Reconcile by paragraph position rather than deleting all IDs (bookmarks survive).
                existing = {p.paragraph_number: p for p in entity.paragraphs}
                for n, parsed_p in enumerate(parsed.paragraphs, 1):
                    paragraph = existing.pop(n, None)
                    if paragraph is None:
                        paragraph = Paragraph(paragraph_number=n)
                        entity.paragraphs.append(paragraph)
                    paragraph.markdown_content, paragraph.plain_text = parsed_p.markdown, parsed_p.plain
                    paragraph.char_count = len(parsed_p.plain)
                for paragraph in existing.values():
                    entity.paragraphs.remove(paragraph)
                entity.paragraph_count = len(parsed.paragraphs)
                kind = "chapter"
            session.flush()
            if state is None:
                state = SyncState(github_path=file.path)
                session.add(state)
                states[file.path] = state
            state.github_sha, state.entity_type, state.entity_id = file.sha, kind, entity.id
            state.sync_status, state.error_message = "synced", None
            state.last_synced_at = datetime.now(timezone.utc)
            session.commit()
            report["created" if created else "updated"] += 1
        except (GitHubError, ParseError, ValueError) as exc:
            session.rollback()
            # Discard objects from rolled-back inserts; retain the previous successful SHA.
            books = {x.github_path: x for x in session.scalars(select(Book))}
            volumes = {x.github_path: x for x in session.scalars(select(Volume))}
            docs = {x.github_path: x for x in session.scalars(select(SourceDocument))}
            state = session.scalar(select(SyncState).where(SyncState.github_path == file.path))
            if state is None:
                state = SyncState(github_path=file.path, github_sha=file.sha,
                                  entity_type="metadata" if is_readme(file.path) else "chapter")
                session.add(state)
            state.sync_status, state.error_message = "error", str(exc)
            states[file.path] = state
            session.commit()
            report["errors"].append({"path": file.path, "message": str(exc)})

    # Snapshot is complete and validated before this function starts. Failed files remain present.
    for path, state in states.items():
        if path in paths or state.sync_status == "deactivated":
            continue
        model = Chapter if state.entity_type == "chapter" else SourceDocument
        entity = session.get(model, state.entity_id) if state.entity_id else None
        if entity:
            entity.is_active = False
        state.sync_status = "deactivated"
        report["deactivated"] += 1
    roots = {p.split("/")[0] for p in paths if "/" in p}
    active_volumes = {map_path(p).volume_path for p in paths if "/" in p}
    for root, book in books.items():
        book.is_active = root in roots
        if book.is_active:
            # Refresh titles after README-only updates too, without reparsing unchanged chapters.
            parent(f"{root}/placeholder.md")
    for vp, volume in volumes.items():
        volume.is_active = vp in active_volumes
    for path in chapter_paths:
        session.execute(update(Chapter).where(Chapter.github_path == path).values(sort_order=ordering[path]))
    # Preserve empty books/volumes declared only by README files.
    for path in sorted(paths, key=natural_key):
        if is_readme(path) and "/" in path:
            parent(path)
    run.status = "partial" if report["errors"] else "completed"
    run.finished_at, run.report = datetime.now(timezone.utc), report
    session.commit()
    return report


def run_sync(session: Session, source: GitHubClient):
    with sync_lock(session.get_bind(), source.repository):
        return sync_snapshot(session, source, source.snapshot())
