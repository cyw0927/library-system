import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteFile:
    path: str
    sha: str


@dataclass(frozen=True)
class Snapshot:
    commit: str
    files: list[RemoteFile]


def is_target(path: str) -> bool:
    return path.lower().endswith(".md") and path.split("/")[0] not in {"tools", ".github"}


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


class GitHubClient:
    """GET-only client; every download is pinned to the tree's commit and blob SHA."""

    def __init__(self, repository: str, branch="main", token="", cache_dir="", transport=None):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("Invalid GitHub repository")
        self.repository, self.branch = repository, branch
        self.cache = Path(cache_dir).resolve() if cache_dir else None
        self.client = httpx.Client(timeout=30, transport=transport, follow_redirects=False)
        self.headers = {"User-Agent": "Library-App", "Accept": "application/vnd.github+json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def close(self):
        self.client.close()

    def _get(self, url, api=False):
        for attempt in range(3):
            try:
                response = self.client.get(url, headers=self.headers if api else {"User-Agent": "Library-App"})
            except httpx.TransportError:
                if attempt == 2:
                    raise GitHubError("GitHub request timed out or could not connect") from None
                time.sleep(attempt + 1)
                continue
            if response.status_code == 200:
                return response
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(attempt + 1)
                continue
            raise GitHubError(f"GitHub HTTP {response.status_code}; existing database was preserved")
        raise GitHubError("GitHub retry limit exceeded")

    def snapshot(self) -> Snapshot:
        base = f"https://api.github.com/repos/{self.repository}"
        commit = self._get(f"{base}/commits/{quote(self.branch, safe='')}", api=True).json()
        data = self._get(f"{base}/git/trees/{commit['commit']['tree']['sha']}?recursive=1", api=True).json()
        if data.get("truncated") or not isinstance(data.get("tree"), list):
            raise GitHubError("Incomplete GitHub tree; refusing to deactivate files")
        files = [RemoteFile(x["path"], x["sha"]) for x in data["tree"] if x["type"] == "blob" and is_target(x["path"])]
        if not files:
            raise GitHubError("Empty Markdown snapshot; refusing to deactivate files")
        return Snapshot(commit["sha"], sorted(files, key=lambda x: x.path))

    def content(self, file: RemoteFile, commit: str) -> str:
        if file.path.startswith("/") or ".." in file.path.split("/"):
            raise GitHubError("Unsafe repository path")
        raw = None
        if self.cache:
            target = (self.cache / file.path).resolve()
            if target.is_relative_to(self.cache) and target.is_file():
                candidate = target.read_bytes()
                if blob_sha(candidate) == file.sha:
                    raw = candidate
        if raw is None:
            url = f"https://raw.githubusercontent.com/{self.repository}/{commit}/{quote(file.path, safe='/')}"
            raw = self._get(url).content
        if blob_sha(raw) != file.sha:
            raise GitHubError("Downloaded blob SHA mismatch")
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise GitHubError("Markdown file is not UTF-8") from None
