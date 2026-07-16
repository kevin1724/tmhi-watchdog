import importlib
import sys

from fastapi.testclient import TestClient


def load_main(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCHDOG_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "watchdog.db"))
    monkeypatch.setenv("API_TOKEN", "test-token")
    sys.modules.pop("tmhi_watchdog.main", None)
    return importlib.import_module("tmhi_watchdog.main")


def test_dashboard_is_served(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Watchdog Console" in response.text


def test_check_series_endpoint(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)

    class FakeWatchdog:
        async def stop(self) -> None:
            pass

        async def check_series(self, *, count: int, interval_seconds: float):
            return {
                "requested_count": count,
                "completed_count": count,
                "interval_seconds": interval_seconds,
                "results": [],
            }

    with TestClient(main.app) as client:
        main.watchdog = FakeWatchdog()
        response = client.post(
            "/api/check/series",
            headers={"X-API-Token": "test-token"},
            json={"count": 2, "interval_seconds": 0},
        )

    assert response.status_code == 200
    assert response.json()["requested_count"] == 2


def test_gateway_test_accepts_supplied_password(monkeypatch, tmp_path) -> None:
    main = load_main(monkeypatch, tmp_path)
    passwords: list[str] = []

    class FakeGatewayClient:
        def __init__(
            self,
            _base_url: str,
            _username: str,
            password: str,
            _timeout_seconds: float,
            _user_agent: str,
        ) -> None:
            passwords.append(password)

        async def is_reachable(self) -> bool:
            return True

        async def authenticate(self) -> str:
            return "token"

        async def close(self) -> None:
            pass

    monkeypatch.setattr(main, "UnifiedGatewayClient", FakeGatewayClient)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/gateway/test",
            headers={"X-API-Token": "test-token"},
            json={"gateway_password": "entered-password"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "reachable": True,
        "authenticated": True,
        "used_supplied_password": True,
    }
    assert passwords == ["entered-password"]
