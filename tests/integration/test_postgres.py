import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="Set TEST_DATABASE_URL to a dedicated PostgreSQL test database"
)


def test_alembic_upgrade_and_percent_encoded_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    from app.core.config import get_settings

    get_settings.cache_clear()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    try:
        command.upgrade(config, "head")
        command.check(config)
        engine = create_engine(DATABASE_URL)
        try:
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT 1")) == 1
            # Phase 1 must not create the Phase 2 library models.
            assert "books" not in inspect(engine).get_table_names()
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()


def test_real_server_with_postgres():
    env = os.environ.copy()
    env["DATABASE_URL"] = DATABASE_URL
    process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", "8010",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with httpx.Client(base_url="http://127.0.0.1:8010", timeout=5, trust_env=False) as client:
            for attempt in range(100):
                if process.poll() is not None:
                    raise AssertionError(process.stderr.read())
                try:
                    response = client.get("/health")
                    break
                except httpx.ConnectError:
                    time.sleep(0.1)
            else:
                raise AssertionError("Uvicorn did not start in 10 seconds")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
            response = client.get("/health/db")
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "database": "ok"}
            assert client.get("/docs").status_code == 200
            print("Live Uvicorn: /health=200, /health/db=200, /docs=200")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
