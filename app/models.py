from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass(slots=True)
class ProbeResult:
    url: str
    success: bool
    latency_ms: float | None = None
    status_code: int | None = None
    error: str | None = None


@dataclass(slots=True)
class ConnectivityResult:
    online: bool
    checked_at: datetime
    successful_probes: int
    required_successes: int
    probes: list[ProbeResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "online": self.online,
            "checked_at": self.checked_at.isoformat(),
            "successful_probes": self.successful_probes,
            "required_successes": self.required_successes,
            "probes": [asdict(item) for item in self.probes],
        }


@dataclass(slots=True)
class RebootResult:
    accepted: bool
    uncertain: bool = False
    message: str = ""


@dataclass(slots=True)
class GatewayDetection:
    reachable: bool
    api_type: str | None = None
    supported: bool = False
    model: str | None = None
    manufacturer: str | None = None
    name: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "api_type": self.api_type,
            "supported": self.supported,
            "model": self.model,
            "manufacturer": self.manufacturer,
            "name": self.name,
            "error": self.error,
        }


@dataclass(slots=True)
class RuntimeState:
    phase: str = "initializing"
    service_started_at: datetime = field(default_factory=utc_now)
    last_check_at: datetime | None = None
    internet_online: bool | None = None
    successful_probes: int = 0
    total_probes: int = 0
    last_probe_results: list[dict[str, Any]] = field(default_factory=list)
    failure_started_at: datetime | None = None
    last_online_at: datetime | None = None
    last_reboot_at: datetime | None = None
    startup_grace_until: datetime | None = None
    post_reboot_grace_until: datetime | None = None
    cooldown_until: datetime | None = None
    gateway_reachable: bool | None = None
    gateway_api_type: str | None = None
    gateway_supported: bool | None = None
    gateway_model: str | None = None
    gateway_manufacturer: str | None = None
    gateway_name: str | None = None
    gateway_error: str | None = None
    reboot_count_24h: int = 0
    last_error: str | None = None

    def to_dict(self, now: datetime, *, dry_run: bool, watchdog_enabled: bool) -> dict[str, Any]:
        outage_seconds = None
        if self.failure_started_at is not None:
            outage_seconds = max(0, int((now - self.failure_started_at).total_seconds()))

        return {
            "phase": self.phase,
            "service_started_at": self.service_started_at.isoformat(),
            "last_check_at": iso_or_none(self.last_check_at),
            "internet_online": self.internet_online,
            "successful_probes": self.successful_probes,
            "total_probes": self.total_probes,
            "last_probe_results": self.last_probe_results,
            "failure_started_at": iso_or_none(self.failure_started_at),
            "outage_seconds": outage_seconds,
            "last_online_at": iso_or_none(self.last_online_at),
            "last_reboot_at": iso_or_none(self.last_reboot_at),
            "startup_grace_until": iso_or_none(self.startup_grace_until),
            "post_reboot_grace_until": iso_or_none(self.post_reboot_grace_until),
            "cooldown_until": iso_or_none(self.cooldown_until),
            "gateway_reachable": self.gateway_reachable,
            "gateway_api_type": self.gateway_api_type,
            "gateway_supported": self.gateway_supported,
            "gateway_model": self.gateway_model,
            "gateway_manufacturer": self.gateway_manufacturer,
            "gateway_name": self.gateway_name,
            "gateway_error": self.gateway_error,
            "reboot_count_24h": self.reboot_count_24h,
            "last_error": self.last_error,
            "dry_run": dry_run,
            "watchdog_enabled": watchdog_enabled,
        }
