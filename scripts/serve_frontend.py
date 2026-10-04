"""Production Streamlit launcher; only the UI cookie secret is mounted here."""
import os
from pathlib import Path
import sys


def main():
    secret = Path("/run/secrets/streamlit_cookie_secret").read_text(encoding="utf-8").strip()
    if len(secret) < 32:
        raise SystemExit("Set a randomly generated Streamlit cookie secret (32+ characters)")
    host = os.environ.get("PUBLIC_HOST", "").strip()
    if not host or host == "library.example.com" or any(char in host for char in "/: "):
        raise SystemExit("Set PUBLIC_HOST to your real hostname (no scheme/port)")
    os.environ["STREAMLIT_SERVER_COOKIE_SECRET"] = secret
    args = [sys.executable, "-m", "streamlit", "run", "frontend/streamlit_app.py",
            "--server.address", "0.0.0.0", "--server.port", "8501", "--server.headless", "true",
            "--server.enableCORS", "true", "--server.enableXsrfProtection", "true",
            "--browser.gatherUsageStats", "false", "--browser.serverAddress", host,
            "--browser.serverPort", "443"]
    os.execv(sys.executable, args)


if __name__ == "__main__":
    main()
