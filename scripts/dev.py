"""Start both localhost servers with a shared, ephemeral private-operation token."""
import argparse
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

from app.core.config import get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--ui-port", type=int, default=8501)
    args = parser.parse_args()
    if not all(1024 <= port <= 65535 for port in (args.api_port, args.ui_port)) or args.api_port == args.ui_port:
        parser.error("Choose different ports between 1024 and 65535")
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "ADMIN_TOKEN": get_settings().admin_token or secrets.token_urlsafe(32),
           "LIBRARY_API_URL": f"http://127.0.0.1:{args.api_port}", "PYTHONUTF8": "1"}
    runtime = root / "work"
    runtime.mkdir(exist_ok=True)
    processes = []
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        with (runtime / "api.log").open("a", encoding="utf-8") as api_log, (runtime / "frontend.log").open("a", encoding="utf-8") as ui_log:
            backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.api_port)], cwd=root, env=env, stdout=api_log, stderr=api_log, creationflags=flags)
            processes.append(backend)
            for attempt in range(100):
                if backend.poll() is not None:
                    raise RuntimeError("Backend exited; see work/api.log")
                try:
                    response = httpx.get(env["LIBRARY_API_URL"] + "/health/db", timeout=2, trust_env=False)
                    if response.status_code != 200:
                        raise RuntimeError("Database unavailable; set DATABASE_URL and apply migrations")
                    break
                except httpx.ConnectError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Backend did not start")
            frontend = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "frontend/streamlit_app.py", "--server.address", "127.0.0.1", "--server.port", str(args.ui_port), "--server.headless", "true", "--browser.gatherUsageStats", "false"], cwd=root, env=env, stdout=ui_log, stderr=ui_log, creationflags=flags)
            processes.append(frontend)
            print(f"Reader: http://127.0.0.1:{args.ui_port}\nAPI: {env['LIBRARY_API_URL']}/docs\nCtrl+C stops both servers.", flush=True)
            while all(p.poll() is None for p in processes):
                time.sleep(0.5)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
