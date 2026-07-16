from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from .config import Settings
from .models import ConnectivityResult, RebootResult, RuntimeState, utc_now
from .storage import EventStore


logger = logging.getLogger(__name__)


class ConnectivityCheckerProtocol(Protocol):
    async def check(self) -> ConnectivityResult: ...


class GatewayProtocol(Protocol):
    async def is_reachable(self) -> bool: ...
    async def authenticate(self) -> str: ...
    async def reboot(self) -> RebootResult: ...


REBOOT_EVENT_KINDS = {"reboot_requested", "reboot_uncertain"}


class Watchdog:
    def __init__(
        self,
        settings: Settings,
        checker: ConnectivityCheckerProtocol,
        gateway: GatewayProtocol,
        store: EventStore,
    ) -> None:
        self.settings = settings
        self.checker = checker
        self.gateway = gateway
        self.store = store
        self.state = RuntimeState()
        self._state_lock = asyncio.Lock()
        self._cycle_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._last_announced_phase: str | None = None

    async def initialize(self) -> None:
        now = utc_now()
        last_reboot = await self.store.latest_timestamp(REBOOT_EVENT_KINDS)
        async with self._state_lock:
            self.state.startup_grace_until = now + timedelta(
                seconds=self.settings.startup_grace_seconds
            )
            self.state.last_reboot_at = last_reboot
            if last_reboot:
                self.state.post_reboot_grace_until = last_reboot + timedelta(
                    seconds=self.settings.post_reboot_grace_seconds
                )
                self.state.cooldown_until = last_reboot + timedelta(
                    seconds=self.settings.reboot_cooldown_seconds
                )
            self.state.reboot_count_24h = await self.store.reboots_last_24h(now)
        await self.store.record(
            "service_started",
            "Watchdog service started",
            self.settings.safe_summary(),
            timestamp=now,
        )

    async def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        await self.initialize()
        if not self.settings.watchdog_enabled:
            await self._set_phase("disabled")
            logger.warning("Watchdog loop is disabled by configuration")
            return

        while not self._stop_event.is_set():
            try:
                await self.check_once(allow_reboot=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep the watchdog alive after an unexpected error
                logger.exception("Unexpected watchdog cycle error")
                async with self._state_lock:
                    self.state.phase = "error"
                    self.state.last_error = f"{type(exc).__name__}: {exc}"
                await self.store.record(
                    "watchdog_error",
                    "Unexpected watchdog cycle error",
                    {"error": f"{type(exc).__name__}: {exc}"},
                )

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.settings.check_interval_seconds,
                )
            except TimeoutError:
                pass

    async def status_snapshot(self) -> dict[str, Any]:
        now = utc_now()
        async with self._state_lock:
            self.state.reboot_count_24h = await self.store.reboots_last_24h(now)
            return self.state.to_dict(
                now,
                dry_run=self.settings.dry_run,
                watchdog_enabled=self.settings.watchdog_enabled,
            )

    async def check_once(self, *, allow_reboot: bool) -> dict[str, Any]:
        async with self._cycle_lock:
            result = await self.checker.check()
            await self._apply_connectivity_result(result, allow_reboot=allow_reboot)
            return await self.status_snapshot()

    async def check_series(
        self, *, count: int, interval_seconds: float
    ) -> dict[str, Any]:
        if count < 1:
            raise ValueError("count must be at least 1")
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be at least 0")

        started_at = utc_now()
        results: list[dict[str, Any]] = []
        for index in range(count):
            snapshot = await self.check_once(allow_reboot=False)
            results.append({"index": index + 1, "status": snapshot})
            if index < count - 1 and interval_seconds > 0:
                await asyncio.sleep(interval_seconds)

        return {
            "started_at": started_at.isoformat(),
            "finished_at": utc_now().isoformat(),
            "requested_count": count,
            "completed_count": len(results),
            "interval_seconds": interval_seconds,
            "results": results,
        }

    async def _apply_connectivity_result(
        self, result: ConnectivityResult, *, allow_reboot: bool
    ) -> None:
        now = result.checked_at
        async with self._state_lock:
            previous_online = self.state.internet_online
            self.state.last_check_at = now
            self.state.internet_online = result.online
            self.state.successful_probes = result.successful_probes
            self.state.total_probes = len(result.probes)
            self.state.last_probe_results = [asdict(item) for item in result.probes]
            self.state.last_error = None

        if result.online:
            async with self._state_lock:
                self.state.phase = "online"
                self.state.last_online_at = now
                self.state.failure_started_at = None
                self.state.gateway_reachable = None
                self.state.post_reboot_grace_until = (
                    None
                    if self.state.post_reboot_grace_until
                    and now >= self.state.post_reboot_grace_until
                    else self.state.post_reboot_grace_until
                )
            if previous_online is False:
                await self.store.record(
                    "internet_restored",
                    "Internet connectivity was restored",
                    {"successful_probes": result.successful_probes},
                    timestamp=now,
                )
                logger.info("Internet connectivity restored")
            await self._announce_phase_if_changed()
            return

        async with self._state_lock:
            startup_grace_until = self.state.startup_grace_until
            reboot_grace_until = self.state.post_reboot_grace_until

        if startup_grace_until and now < startup_grace_until:
            await self._set_phase("startup_grace")
            return

        if reboot_grace_until and now < reboot_grace_until:
            await self._set_phase("post_reboot_grace")
            return

        async with self._state_lock:
            if self.state.failure_started_at is None:
                self.state.failure_started_at = now
                first_failure = True
            else:
                first_failure = False
            failure_started_at = self.state.failure_started_at

        if first_failure:
            await self.store.record(
                "internet_lost",
                "All required internet connectivity checks failed",
                {
                    "successful_probes": result.successful_probes,
                    "required_successes": result.required_successes,
                },
                timestamp=now,
            )
            logger.warning("Internet connectivity checks are failing")

        outage_seconds = (now - failure_started_at).total_seconds()
        if outage_seconds < self.settings.failure_threshold_seconds:
            await self._set_phase("confirming_outage")
            return

        if not allow_reboot:
            await self._set_phase("outage_confirmed")
            return

        await self._attempt_automatic_reboot(now)

    async def _attempt_automatic_reboot(self, now: datetime) -> None:
        reboot_count = await self.store.reboots_last_24h(now)
        async with self._state_lock:
            self.state.reboot_count_24h = reboot_count
            cooldown_until = self.state.cooldown_until

        if cooldown_until and now < cooldown_until:
            await self._set_phase("reboot_cooldown")
            return

        if reboot_count >= self.settings.max_reboots_per_24h:
            previous_phase = await self._get_phase()
            await self._set_phase("reboot_limit_reached")
            if previous_phase != "reboot_limit_reached":
                await self.store.record(
                    "reboot_limit_reached",
                    "Automatic reboot limit reached",
                    {
                        "count": reboot_count,
                        "limit": self.settings.max_reboots_per_24h,
                    },
                    timestamp=now,
                )
            return

        reachable = await self.gateway.is_reachable()
        async with self._state_lock:
            self.state.gateway_reachable = reachable
        if not reachable:
            previous_phase = await self._get_phase()
            await self._set_phase("gateway_unreachable")
            if previous_phase != "gateway_unreachable":
                await self.store.record(
                    "gateway_unreachable",
                    "Internet is down and the gateway local API is unreachable",
                    timestamp=now,
                )
            return

        await self._perform_reboot(now, source="automatic", force=False)

    async def manual_reboot(self, *, force: bool = False) -> dict[str, Any]:
        async with self._cycle_lock:
            now = utc_now()
            if not force:
                reboot_count = await self.store.reboots_last_24h(now)
                async with self._state_lock:
                    cooldown_until = self.state.cooldown_until
                if cooldown_until and now < cooldown_until:
                    raise RuntimeError(
                        f"Reboot cooldown is active until {cooldown_until.isoformat()}"
                    )
                if reboot_count >= self.settings.max_reboots_per_24h:
                    raise RuntimeError("Reboot limit for the last 24 hours has been reached")

            reachable = await self.gateway.is_reachable()
            if not reachable:
                raise RuntimeError("Gateway local API is not reachable")
            await self._perform_reboot(now, source="manual", force=force)
            return await self.status_snapshot()

    async def test_gateway_login(self) -> dict[str, Any]:
        reachable = await self.gateway.is_reachable()
        if not reachable:
            return {"reachable": False, "authenticated": False}
        if self.settings.dry_run and not self.settings.gateway_password:
            return {
                "reachable": True,
                "authenticated": False,
                "message": "Gateway is reachable; no password is configured for login testing",
            }
        await self.gateway.authenticate()
        return {"reachable": True, "authenticated": True}

    async def _perform_reboot(
        self, now: datetime, *, source: str, force: bool
    ) -> None:
        if self.settings.dry_run:
            await self.store.record(
                "reboot_dry_run",
                "Dry run: gateway reboot would have been requested",
                {"source": source, "force": force},
                timestamp=now,
            )
            logger.warning("DRY RUN: gateway reboot would have been requested")
            async with self._state_lock:
                self.state.phase = "dry_run_reboot"
                self.state.failure_started_at = None
                self.state.gateway_reachable = True
            return

        await self._set_phase("rebooting")
        try:
            result = await self.gateway.reboot()
        except Exception as exc:
            async with self._state_lock:
                self.state.phase = "reboot_failed"
                self.state.last_error = f"{type(exc).__name__}: {exc}"
            await self.store.record(
                "reboot_failed",
                "Gateway reboot request failed",
                {"source": source, "error": f"{type(exc).__name__}: {exc}"},
                timestamp=now,
            )
            logger.exception("Gateway reboot request failed")
            return

        kind = "reboot_uncertain" if result.uncertain else "reboot_requested"
        await self.store.record(
            kind,
            result.message or "Gateway reboot requested",
            {"source": source, "force": force, "uncertain": result.uncertain},
            timestamp=now,
        )
        async with self._state_lock:
            self.state.phase = "post_reboot_grace"
            self.state.last_reboot_at = now
            self.state.failure_started_at = None
            self.state.post_reboot_grace_until = now + timedelta(
                seconds=self.settings.post_reboot_grace_seconds
            )
            self.state.cooldown_until = now + timedelta(
                seconds=self.settings.reboot_cooldown_seconds
            )
            self.state.reboot_count_24h = await self.store.reboots_last_24h(now)
        logger.warning("Gateway reboot requested: %s", result.message)

    async def _get_phase(self) -> str:
        async with self._state_lock:
            return self.state.phase

    async def _set_phase(self, phase: str) -> None:
        async with self._state_lock:
            self.state.phase = phase
        await self._announce_phase_if_changed()

    async def _announce_phase_if_changed(self) -> None:
        async with self._state_lock:
            phase = self.state.phase
        if phase != self._last_announced_phase:
            logger.info("Watchdog phase changed: %s", phase)
            self._last_announced_phase = phase
