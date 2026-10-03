import hashlib
import base64
import os
import re
import subprocess
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

    def __init__(self, repository: str, branch="main", token="", cache_dir="", transport=None, use_git_credentials=False):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("Invalid GitHub repository")
        self.repository, self.branch = repository, branch
        self.cache = Path(cache_dir).resolve() if cache_dir else None
        self.client = httpx.Client(timeout=30, transport=transport, follow_redirects=False)
        self.headers = {"User-Agent": "Library-App", "Accept": "application/vnd.github+json"}
        if not token and use_git_credentials:
            # Explicit opt-in: use the existing login, never persist or print its credential.
            try:
                root = Path(__file__).resolve().parents[2]
                credential = subprocess.run(
                    ["git", "-c", f"safe.directory={root.as_posix()}", "-c", "credential.interactive=never", "credential", "fill"],
                    input="protocol=https\nhost=github.com\n\n", capture_output=True, text=True,
                    timeout=15, env={**os.environ, "GCM_INTERACTIVE": "never"}, check=True)
                token = next((line.removeprefix("password=") for line in credential.stdout.splitlines() if line.startswith("password=")), "")
            except (OSError, subprocess.SubprocessError):
                raise GitHubError("Git credential unavailable; configure GITHUB_TOKEN") from None
            if not token:
                raise GitHubError("Git credential unavailable; configure GITHUB_TOKEN")
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
            # Blob API supports private repositories. Credentials stay on api.github.com only.
            if not re.fullmatch(r"[a-fA-F0-9]{40}", file.sha):
                raise GitHubError("Invalid GitHub blob SHA")
            url = f"https://api.github.com/repos/{self.repository}/git/blobs/{file.sha}"
            try:
                blob = self._get(url, api=True).json()
                if blob["encoding"] != "base64":
                    raise ValueError()
                raw = base64.b64decode("".join(blob["content"].split()), validate=True)
            except (ValueError, KeyError, TypeError):
                raise GitHubError("GitHub returned an invalid blob") from None
        if blob_sha(raw) != file.sha:
            raise GitHubError("Downloaded blob SHA mismatch")
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise GitHubError("Markdown file is not UTF-8") from None
