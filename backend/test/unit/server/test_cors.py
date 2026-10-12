from fastapi.testclient import TestClient

from server.main import app


def test_local_dev_origin_is_allowed():
    response = TestClient(app).options(
        "/api/system/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unknown_origin_is_not_allowed():
    response = TestClient(app).options(
        "/api/system/health",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
