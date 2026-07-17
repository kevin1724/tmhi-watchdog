from __future__ import annotations

import os
import re
from pathlib import Path


DEFAULT_MANAGED_ENV_PATH = "/data/watchdog.env"
DEFAULT_MANAGED_ENV_VALUES: tuple[tuple[str, str], ...] = (
    ("GATEWAY_HOST", "192.168.12.1"),
    ("GATEWAY_PORT", "8080"),
    ("GATEWAY_USERNAME", "admin"),
    ("GATEWAY_PASSWORD", ""),
    ("DRY_RUN", "true"),
    ("WATCHDOG_ENABLED", "true"),
    ("CHECK_INTERVAL_SECONDS", "20"),
    ("FAILURE_THRESHOLD_SECONDS", "180"),
    ("STARTUP_GRACE_SECONDS", "60"),
    ("POST_REBOOT_GRACE_SECONDS", "480"),
    ("REBOOT_COOLDOWN_SECONDS", "1800"),
    ("MAX_REBOOTS_PER_24H", "3"),
    ("PROBE_TIMEOUT_SECONDS", "5"),
    ("MINIMUM_SUCCESSFUL_PROBES", "2"),
    (
        "PROBE_URLS",
        (
            "https://connectivitycheck.gstatic.com/generate_204,"
            "https://www.cloudflare.com/cdn-cgi/trace,"
            "http://www.msftconnecttest.com/connecttest.txt"
        ),
    ),
    ("DATABASE_PATH", "/data/watchdog.db"),
    ("LOG_LEVEL", "INFO"),
    ("CORS_ORIGINS", ""),
)
_ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_UNQUOTED_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_./:,@%+=-]*$")


class ManagedEnvFile:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def ensure_exists(self) -> None:
        if self.path.exists():
            return
        self._write_lines(self._default_lines())

    def load(self) -> dict[str, str]:
        self.ensure_exists()
        values: dict[str, str] = {}
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return values

        for line in lines:
            parsed = _parse_env_line(line)
            if parsed is not None:
                key, value = parsed
                values[key] = value
        return values

    def set_value(self, key: str, value: str) -> bool:
        _validate_env_key(key)
        previous_value = self.load().get(key, "")
        lines = self._read_lines()
        replacement = f"{key}={_format_env_value(value)}"
        updated = False
        next_lines: list[str] = []

        for line in lines:
            parsed = _parse_env_line(line)
            if parsed is not None and parsed[0] == key:
                next_lines.append(replacement)
                updated = True
            else:
                next_lines.append(line)

        if not updated:
            if next_lines and next_lines[-1].strip():
                next_lines.append("")
            next_lines.append(replacement)

        self._write_lines(next_lines)
        return previous_value != value

    def clear_value(self, key: str) -> bool:
        previous_value = self.load().get(key, "")
        self.set_value(key, "")
        return bool(previous_value)

    def _read_lines(self) -> list[str]:
        self.ensure_exists()
        try:
            return self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return self._default_lines()

    def _write_lines(self, lines: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        os.replace(temporary_path, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _default_lines() -> list[str]:
        return [
            "# TMHI Gateway Watchdog settings",
            "# This file is created and updated by the app inside the Docker data volume.",
            *[
                f"{key}={_format_env_value(value)}"
                for key, value in DEFAULT_MANAGED_ENV_VALUES
            ],
        ]


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[7:].lstrip()
    if "=" not in stripped:
        return None

    key, raw_value = stripped.split("=", 1)
    key = key.strip()
    if not _ENV_KEY_PATTERN.fullmatch(key):
        return None
    return key, _parse_env_value(raw_value)


def _parse_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        quote = value[0]
        inner = value[1:-1]
        if quote == '"':
            return _unescape_double_quoted_value(inner)
        return inner
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def _unescape_double_quoted_value(value: str) -> str:
    result: list[str] = []
    escaped = False
    for character in value:
        if escaped:
            result.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        else:
            result.append(character)
    if escaped:
        result.append("\\")
    return "".join(result)


def _format_env_value(value: str) -> str:
    if _UNQUOTED_VALUE_PATTERN.fullmatch(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _validate_env_key(key: str) -> None:
    if not _ENV_KEY_PATTERN.fullmatch(key):
        raise ValueError(f"Invalid environment key: {key}")
