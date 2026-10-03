import httpx
import pytest

from app.services.github_client import GitHubClient, GitHubError, RemoteFile, blob_sha, is_target


def test_markdown_selection():
    assert is_target("Book/README.md")
    assert is_target("Book/CHAPTER.MD")
    assert not is_target("tools/how.md")
    assert not is_target(".github/guide.md")


def test_truncated_tree_is_rejected():
    def handler(request):
        if "/commits/" in str(request.url):
            return httpx.Response(200, json={"sha": "commit", "commit": {"tree": {"sha": "tree"}}})
        return httpx.Response(200, json={"truncated": True, "tree": []})
    source = GitHubClient("owner/repo", transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubError, match="Incomplete"):
        source.snapshot()
    source.close()


def test_blob_sha_and_cache(tmp_path):
    content = "# 장\n\n본문".encode()
    (tmp_path / "chapter.md").write_bytes(content)
    source = GitHubClient("owner/repo", cache_dir=str(tmp_path))
    assert source.content(RemoteFile("chapter.md", blob_sha(content)), "commit") == content.decode()
    with pytest.raises(GitHubError, match="Unsafe"):
        source.content(RemoteFile("../outside.md", "sha"), "commit")
    source.close()
