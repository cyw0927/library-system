import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.services.parser_service import MARKDOWN, plain_text


def natural_key(value: str):
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r"(\d+)", value))


def slug(value: str) -> str:
    return re.sub(r"[^\w-]+", "-", value.casefold()).strip("-")


def readable(value: str) -> str:
    return re.sub(r"^\d+_", "", value).replace("_", " ")


def is_readme(path: str) -> bool:
    return PurePosixPath(path).name.casefold() == "readme.md"


@dataclass(frozen=True)
class PathMetadata:
    book_path: str
    volume_path: str | None
    number: int | None
    code: str
    pov: str | None


def map_path(path: str) -> PathMetadata:
    parts = PurePosixPath(path).parts
    if len(parts) < 2:
        raise ValueError("Root Markdown is library metadata, not a chapter")
    code = PurePosixPath(path).stem
    number = re.match(r"(?:chapter[_ -])?(\d+)(?:_|$)", code, re.I)
    explicit_pov = re.fullmatch(r"\d+_([A-Za-z]+(?:_[A-Za-z]+)*)_\d+", code)
    volume = None
    if len(parts) >= 3 and not re.fullmatch(r"\d+_\d+[-–]\d+", parts[1]):
        volume = "/".join(parts[:2])
    return PathMetadata(parts[0], volume, int(number[1]) if number else None,
                        code, explicit_pov[1].replace("_", " ") if explicit_pov else None)


def readme_metadata(source: str, fallback: str) -> dict:
    tokens = MARKDOWN.parse(source)
    lines = source.splitlines()
    heading = next((t for t in tokens if t.type == "heading_open" and t.tag == "h1"), None)
    title = plain_text("\n".join(lines[heading.map[0]:heading.map[1]])) if heading else readable(fallback)
    introductory = source.split("\n## ", 1)[0]
    author = None
    for pattern in [r"(?:저자|원작)\s*[:：]\s*([^,\n]+)", r"\n\s*([^\n]+?)의\s*[*『《]", r"\n\s*([^\n]+?),\s*\*[^*]+\*"]:
        match = re.search(pattern, introductory)
        if match:
            author = plain_text(match[1]).strip("- ")[:500]
            break
    # Only explicit totals are authoritative. Unknown totals stay null, never guessed.
    total = re.search(r"(?:전체|합계|총)\s*[^\n]*?(?:\d+\s*/\s*)?(\d+)\s*장", source)
    expected = int(total[1]) if total else None
    fractions = re.findall(r"(\d+)\s*/\s*(\d+)\s*(?:장)?\s*(?:번역|완료|완역|진행)", plain_text(source))
    status = "unknown"
    if fractions:
        status = "complete" if all(int(a) == int(b) for a, b in fractions) else "in_progress"
    elif re.search(r"번역 완료|전권 완역|전체.*완료", introductory):
        status = "complete"
    return {"title": title[:500], "original_title": readable(fallback)[:500], "author": author,
            "description": plain_text(introductory), "status": status, "expected_chapters": expected}
