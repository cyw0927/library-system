from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_health(client: TestClient) -> None:
    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_database_health_reports_failure(unavailable_db_client: TestClient) -> None:
    response = unavailable_db_client.get("/health/db")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}



def test_database_failure_does_not_expose_credentials(unavailable_db_client, caplog):
    response = unavailable_db_client.get("/health/db")

    assert response.status_code == 503
    assert "secret password" not in response.text
    assert "secret password" not in caplog.text
    assert "Database health check failed" in caplog.text
