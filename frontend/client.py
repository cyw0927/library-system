import os

import httpx


class APIError(RuntimeError):
    pass


def request(method, path, params=None, body=None):
    url = os.getenv("LIBRARY_API_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.getenv("ADMIN_TOKEN", "")
    try:
        response = httpx.request(method, url + path, params=params, json=body,
                                 headers={"X-Admin-Token": token} if token else {}, timeout=180)
        if response.is_error:
            try:
                detail = response.json().get("detail", "API 요청 실패")
            except ValueError:
                detail = "API 요청 실패"
            raise APIError(f"{response.status_code}: {detail}")
        return response.json() if response.status_code != 204 else None
    except httpx.TransportError:
        raise APIError("API 서버에 연결할 수 없습니다. FastAPI와 DB 상태를 확인하세요.") from None


def get(path, **params):
    return request("GET", path, params={k: v for k, v in params.items() if v is not None})


def post(path, **body):
    return request("POST", path, body=body)
