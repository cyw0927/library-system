import os

import httpx


class APIError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def auth_enabled():
    return os.getenv("APP_ENV", "development") == "production" or os.getenv("AUTH_REQUIRED", "false").lower() in {"true", "1", "yes"}


def request(method, path, params=None, body=None, token=None):
    url = os.getenv("LIBRARY_API_URL", "http://127.0.0.1:8000").rstrip("/")
    headers = {}
    if auth_enabled():
        if token is None:
            import streamlit as st
            token = st.session_state.get("access_token", "")
        if token:
            headers["Authorization"] = "Bearer " + token
    else:
        # Legacy shared admin credentials are NEVER forwarded in authenticated mode.
        legacy = os.getenv("ADMIN_TOKEN", "")
        if token:
            headers["Authorization"] = "Bearer " + token
        elif legacy:
            headers["X-Admin-Token"] = legacy
    try:
        response = httpx.request(method, url + path, params=params, json=body,
                                 headers=headers, timeout=180, trust_env=False)
        if response.is_error:
            try:
                detail = response.json().get("detail", "API 요청 실패")
            except ValueError:
                detail = "API 요청 실패"
            raise APIError(f"{response.status_code}: {detail}", response.status_code)
        return response.json() if response.status_code != 204 else None
    except httpx.TransportError:
        raise APIError("API 서버에 연결할 수 없습니다. FastAPI와 DB 상태를 확인하세요.") from None


def get(path, **params):
    return request("GET", path, params={k: v for k, v in params.items() if v is not None})


def post(path, **body):
    return request("POST", path, body=body)
