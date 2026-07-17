from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .credentials import DEFAULT_MANAGED_ENV_PATH, ManagedEnvFile


DEFAULT_PROBE_URLS = (
    "https://connectivitycheck.gstatic.com/generate_204",
    "https://www.cloudflare.com/cdn-cgi/trace",
    "http://www.msftconnecttest.com/connecttest.txt",
)


def _read_process_secret(name: str, default: str = "") -> str:
    """Read NAME_FILE first, then NAME from the process environment."""
    file_path = os.getenv(f"{name}_FILE", "").strip()
    if file_path:
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"Unable to read {name}_FILE: {exc}") from exc
    return os.getenv(name, default).strip()


def _env(values: dict[str, str], name: str, default: str = "") -> str:
    return os.getenv(name, values.get(name, default)).strip()


def _bool(values: dict[str, str], name: str, default: bool) -> bool:
    raw = os.getenv(name, values.get(name))
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _int(values: dict[str, str], name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, values.get(name))
    value = default if raw is None else int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _float(
    values: dict[str, str],
    name: str,
    default: float,
    minimum: float = 0.0,
) -> float:
    raw = os.getenv(name, values.get(name))
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
    gateway_password_source: str = "none"
    managed_env_path: str = field(default=DEFAULT_MANAGED_ENV_PATH, repr=False)
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
    cors_origins: tuple[str, ...] = ()
    log_level: str = "INFO"

    @property
    def gateway_base_url(self) -> str:
        return f"http://{self.gateway_host}:{self.gateway_port}/TMI/v1"

    @classmethod
    def from_env(cls) -> "Settings":
        process_database_path = os.getenv("DATABASE_PATH", "/data/watchdog.db").strip()
        default_managed_env_path = str(
            Path(process_database_path or "/data/watchdog.db").with_name("watchdog.env")
        )
        managed_env_path = os.getenv(
            "WATCHDOG_ENV_PATH",
            default_managed_env_path,
        ).strip()
        managed_env = ManagedEnvFile(managed_env_path)
        managed_env.ensure_exists()
        managed_values = managed_env.load()

        database_path = _env(managed_values, "DATABASE_PATH", "/data/watchdog.db")
        environment_gateway_password = _read_process_secret("GATEWAY_PASSWORD")
        saved_gateway_password = managed_values.get("GATEWAY_PASSWORD", "").strip()
        gateway_password = saved_gateway_password or environment_gateway_password
        if saved_gateway_password:
            gateway_password_source = "saved"
        elif environment_gateway_password:
            gateway_password_source = "environment"
        else:
            gateway_password_source = "none"

        probe_urls = tuple(
            item.strip()
            for item in _env(
                managed_values,
                "PROBE_URLS",
                ",".join(DEFAULT_PROBE_URLS),
            ).split(",")
            if item.strip()
        )
        cors_origins = tuple(
            item.strip()
            for item in _env(managed_values, "CORS_ORIGINS", "").split(",")
            if item.strip()
        )

        settings = cls(
            gateway_host=_env(managed_values, "GATEWAY_HOST", "192.168.12.1"),
            gateway_port=_int(managed_values, "GATEWAY_PORT", 8080, 1),
            gateway_username=_env(managed_values, "GATEWAY_USERNAME", "admin"),
            gateway_password=gateway_password,
            gateway_password_source=gateway_password_source,
            managed_env_path=managed_env_path,
            gateway_timeout_seconds=_float(
                managed_values,
                "GATEWAY_TIMEOUT_SECONDS",
                15.0,
                1.0,
            ),
            gateway_user_agent=_env(
                managed_values,
                "GATEWAY_USER_AGENT",
                "homeisp/android/2.12.1",
            ),
            watchdog_enabled=_bool(managed_values, "WATCHDOG_ENABLED", True),
            dry_run=_bool(managed_values, "DRY_RUN", True),
            check_interval_seconds=_int(
                managed_values,
                "CHECK_INTERVAL_SECONDS",
                20,
                5,
            ),
            failure_threshold_seconds=_int(
                managed_values,
                "FAILURE_THRESHOLD_SECONDS",
                180,
                30,
            ),
            startup_grace_seconds=_int(
                managed_values,
                "STARTUP_GRACE_SECONDS",
                60,
                0,
            ),
            post_reboot_grace_seconds=_int(
                managed_values,
                "POST_REBOOT_GRACE_SECONDS",
                480,
                60,
            ),
            reboot_cooldown_seconds=_int(
                managed_values,
                "REBOOT_COOLDOWN_SECONDS",
                1800,
                60,
            ),
            max_reboots_per_24h=_int(
                managed_values,
                "MAX_REBOOTS_PER_24H",
                3,
                1,
            ),
            probe_urls=probe_urls,
            probe_timeout_seconds=_float(
                managed_values,
                "PROBE_TIMEOUT_SECONDS",
                5.0,
                1.0,
            ),
            minimum_successful_probes=_int(
                managed_values,
                "MINIMUM_SUCCESSFUL_PROBES",
                2,
                1,
            ),
            database_path=database_path,
            cors_origins=cors_origins,
            log_level=_env(managed_values, "LOG_LEVEL", "INFO").upper(),
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
            "gateway_password_source": self.gateway_password_source,
            "gateway_login_saved": self.gateway_password_source == "saved",
            "watchdog_enabled": self.watchdog_enabled,
            "dry_run": self.dry_run,
            "check_interval_seconds": self.check_interval_seconds,
            "tests_per_hour": round(3600 / self.check_interval_seconds),
            "failure_threshold_seconds": self.failure_threshold_seconds,
            "startup_grace_seconds": self.startup_grace_seconds,
            "post_reboot_grace_seconds": self.post_reboot_grace_seconds,
            "reboot_cooldown_seconds": self.reboot_cooldown_seconds,
            "max_reboots_per_24h": self.max_reboots_per_24h,
            "probe_urls": list(self.probe_urls),
            "minimum_successful_probes": self.minimum_successful_probes,
            "database_path": self.database_path,
            "managed_env_path": self.managed_env_path,
        }
