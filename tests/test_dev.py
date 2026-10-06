from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
from scripts import dev


def test_dev_retries_connect_timeout_while_backend_is_starting(monkeypatch):
    monkeypatch.setattr(dev.sys, "argv", ["scripts.dev"])
    monkeypatch.setattr(dev, "get_settings", lambda: SimpleNamespace(
        auth_enabled=False, admin_token="", app_env="development"))
    backend, frontend = MagicMock(), MagicMock()
    backend.poll.return_value = None
    frontend.poll.return_value = 0
    launch = MagicMock(side_effect=[backend, frontend])
    health = MagicMock(side_effect=[httpx.ConnectTimeout("Starting"), httpx.Response(200)])
    monkeypatch.setattr(dev.subprocess, "Popen", launch)
    monkeypatch.setattr(dev.httpx, "get", health)
    monkeypatch.setattr(dev.time, "sleep", lambda seconds: None)
    dev.main()
    assert health.call_count == 2
    assert launch.call_count == 2
    assert "streamlit" in launch.call_args_list[1].args[0]
    backend.terminate.assert_called_once()