from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_PROBE_URLS = (
    "https://connectivitycheck.gstatic.com/generate_204",
    "https://www.cloudflare.com/cdn-cgi/trace",
    "http://www.msftconnecttest.com/connecttest.txt",
)


def _read_secret(name: str, default: str = "") -> str:
    """Read NAME_FILE first, then NAME. This supports Docker secrets."""
    file_path = os.getenv(f"{name}_FILE", "").strip()
    if file_path:
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"Unable to read {name}_FILE: {exc}") from exc
    return os.getenv(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    value = default if raw is None else float(raw)
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(slots=True)
class Settings:
    gateway_host: str = "192.168.12.1"
    gateway_port: int = 8080
    gateway_username: str = "admin"
    gateway_password: str = field(default="", repr=False)
    gateway_timeout_seconds: float = 15.0
    gateway_user_agent: str = "homeisp/android/2.12.1"

    watchdog_enabled: bool = True
    dry_run: bool = True
    check_interval_seconds: int = 20
    failure_threshold_seconds: int = 180
    startup_grace_seconds: int = 60
    post_reboot_grace_seconds: int = 480
    reboot_cooldown_seconds: int = 1800
    max_reboots_per_24h: int = 3

    probe_urls: tuple[str, ...] = DEFAULT_PROBE_URLS
    probe_timeout_seconds: float = 5.0
    minimum_successful_probes: int = 2

    database_path: str = "/data/watchdog.db"
    api_token: str = field(default="", repr=False)
    cors_origins: tuple[str, ...] = ()
    log_level: str = "INFO"

    @property
    def gateway_base_url(self) -> str:
        return f"http://{self.gateway_host}:{self.gateway_port}/TMI/v1"

    @classmethod
    def from_env(cls) -> "Settings":
        probe_urls = tuple(
            item.strip()
            for item in os.getenv("PROBE_URLS", ",".join(DEFAULT_PROBE_URLS)).split(",")
            if item.strip()
        )
        cors_origins = tuple(
            item.strip()
            for item in os.getenv("CORS_ORIGINS", "").split(",")
            if item.strip()
        )

        settings = cls(
            gateway_host=os.getenv("GATEWAY_HOST", "192.168.12.1").strip(),
            gateway_port=_int("GATEWAY_PORT", 8080, 1),
            gateway_username=os.getenv("GATEWAY_USERNAME", "admin").strip(),
            gateway_password=_read_secret("GATEWAY_PASSWORD"),
            gateway_timeout_seconds=_float("GATEWAY_TIMEOUT_SECONDS", 15.0, 1.0),
            gateway_user_agent=os.getenv(
                "GATEWAY_USER_AGENT", "homeisp/android/2.12.1"
            ).strip(),
            watchdog_enabled=_bool("WATCHDOG_ENABLED", True),
            dry_run=_bool("DRY_RUN", True),
            check_interval_seconds=_int("CHECK_INTERVAL_SECONDS", 20, 5),
            failure_threshold_seconds=_int("FAILURE_THRESHOLD_SECONDS", 180, 30),
            startup_grace_seconds=_int("STARTUP_GRACE_SECONDS", 60, 0),
            post_reboot_grace_seconds=_int("POST_REBOOT_GRACE_SECONDS", 480, 60),
            reboot_cooldown_seconds=_int("REBOOT_COOLDOWN_SECONDS", 1800, 60),
            max_reboots_per_24h=_int("MAX_REBOOTS_PER_24H", 3, 1),
            probe_urls=probe_urls,
            probe_timeout_seconds=_float("PROBE_TIMEOUT_SECONDS", 5.0, 1.0),
            minimum_successful_probes=_int("MINIMUM_SUCCESSFUL_PROBES", 2, 1),
            database_path=os.getenv("DATABASE_PATH", "/data/watchdog.db").strip(),
            api_token=_read_secret("API_TOKEN"),
            cors_origins=cors_origins,
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.gateway_host:
            raise ValueError("GATEWAY_HOST cannot be empty")
        if not self.gateway_username:
            raise ValueError("GATEWAY_USERNAME cannot be empty")
        if not self.probe_urls:
            raise ValueError("At least one PROBE_URL is required")
        if self.minimum_successful_probes > len(self.probe_urls):
            raise ValueError(
                "MINIMUM_SUCCESSFUL_PROBES cannot exceed the number of PROBE_URLS"
            )
        for url in self.probe_urls:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"Invalid probe URL: {url}")
        if self.watchdog_enabled and not self.dry_run and not self.gateway_password:
            raise ValueError(
                "GATEWAY_PASSWORD is required when WATCHDOG_ENABLED=true and DRY_RUN=false"
            )

    def safe_summary(self) -> dict[str, object]:
        return {
            "gateway_host": self.gateway_host,
            "gateway_port": self.gateway_port,
            "gateway_username": self.gateway_username,
            "gateway_password_configured": bool(self.gateway_password),
            "watchdog_enabled": self.watchdog_enabled,
            "dry_run": self.dry_run,
            "check_interval_seconds": self.check_interval_seconds,
            "failure_threshold_seconds": self.failure_threshold_seconds,
            "startup_grace_seconds": self.startup_grace_seconds,
            "post_reboot_grace_seconds": self.post_reboot_grace_seconds,
            "reboot_cooldown_seconds": self.reboot_cooldown_seconds,
            "max_reboots_per_24h": self.max_reboots_per_24h,
            "probe_urls": list(self.probe_urls),
            "minimum_successful_probes": self.minimum_successful_probes,
            "database_path": self.database_path,
            "manual_api_enabled": bool(self.api_token),
        }
