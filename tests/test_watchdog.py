from datetime import timedelta

import pytest

from app.config import Settings
from app.models import ConnectivityResult, ProbeResult, RebootResult, utc_now
from app.storage import EventStore
from app.watchdog import Watchdog


class FakeChecker:
    def __init__(self, online: bool) -> None:
        self.online = online
        self.calls = 0

    async def check(self) -> ConnectivityResult:
        self.calls += 1
        now = utc_now()
        return ConnectivityResult(
            online=self.online,
            checked_at=now,
            successful_probes=2 if self.online else 0,
            required_successes=2,
            probes=[ProbeResult("https://example.test", self.online)],
        )


class FakeGateway:
    def __init__(self) -> None:
        self.reboot_calls = 0
        self.reachable = True

    async def is_reachable(self) -> bool:
        return self.reachable

    async def authenticate(self) -> str:
        return "token"

    async def reboot(self) -> RebootResult:
        self.reboot_calls += 1
        return RebootResult(True, message="accepted")


@pytest.mark.asyncio
async def test_reboots_after_confirmed_outage(tmp_path) -> None:
    settings = Settings(
        gateway_password="secret",
        dry_run=False,
        startup_grace_seconds=0,
        failure_threshold_seconds=30,
        post_reboot_grace_seconds=60,
        reboot_cooldown_seconds=120,
        database_path=str(tmp_path / "watchdog.db"),
    )
    store = EventStore(settings.database_path)
    await store.initialize()
    checker = FakeChecker(False)
    gateway = FakeGateway()
    watchdog = Watchdog(settings, checker, gateway, store)
    await watchdog.initialize()

    await watchdog.check_once(allow_reboot=True)
    watchdog.state.failure_started_at = utc_now() - timedelta(seconds=31)
    await watchdog.check_once(allow_reboot=True)

    assert gateway.reboot_calls == 1
    status = await watchdog.status_snapshot()
    assert status["phase"] == "post_reboot_grace"


@pytest.mark.asyncio
async def test_dry_run_never_calls_gateway_reboot(tmp_path) -> None:
    settings = Settings(
        dry_run=True,
        startup_grace_seconds=0,
        failure_threshold_seconds=30,
        database_path=str(tmp_path / "watchdog.db"),
    )
    store = EventStore(settings.database_path)
    await store.initialize()
    checker = FakeChecker(False)
    gateway = FakeGateway()
    watchdog = Watchdog(settings, checker, gateway, store)
    await watchdog.initialize()

    await watchdog.check_once(allow_reboot=True)
    watchdog.state.failure_started_at = utc_now() - timedelta(seconds=31)
    await watchdog.check_once(allow_reboot=True)

    assert gateway.reboot_calls == 0
    events = await store.recent()
    assert any(event["kind"] == "reboot_dry_run" for event in events)


@pytest.mark.asyncio
async def test_check_series_runs_requested_checks_without_reboot(tmp_path) -> None:
    settings = Settings(
        gateway_password="secret",
        dry_run=False,
        startup_grace_seconds=0,
        failure_threshold_seconds=0,
        database_path=str(tmp_path / "watchdog.db"),
    )
    store = EventStore(settings.database_path)
    await store.initialize()
    checker = FakeChecker(False)
    gateway = FakeGateway()
    watchdog = Watchdog(settings, checker, gateway, store)
    await watchdog.initialize()

    result = await watchdog.check_series(count=3, interval_seconds=0)

    assert result["requested_count"] == 3
    assert result["completed_count"] == 3
    assert len(result["results"]) == 3
    assert checker.calls == 3
    assert gateway.reboot_calls == 0
    assert result["results"][-1]["status"]["phase"] == "outage_confirmed"
