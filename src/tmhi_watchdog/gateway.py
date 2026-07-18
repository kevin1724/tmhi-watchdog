from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from .models import GatewayDetection, RebootResult


logger = logging.getLogger(__name__)


class GatewayError(RuntimeError):
    """Base gateway communication error."""


class GatewayAuthenticationError(GatewayError):
    """Gateway rejected credentials or did not return a token."""


class GatewayUnavailableError(GatewayError):
    """Gateway local API could not be reached."""


class UnifiedGatewayClient:
    """Client for Arcadyan/Sagemcom/Sercomm gateways using the TMI v1 API."""

    AUTH_PATH = "/auth/login"
    INFO_PATHS = ("/gateway/?get=all", "/gateway?get=all")
    REBOOT_PATH = "/gateway/reset?set=reboot"
    NOKIA_STATUS_PATH = "/dashboard_device_status_web_app.cgi"
    NOKIA_INFO_PATH = "/dashboard_device_info_status_web_app.cgi"

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout_seconds: float = 15.0,
        user_agent: str = "homeisp/android/2.12.1",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._tmi_base_urls = _candidate_tmi_base_urls(self.base_url)
        self._active_tmi_base_url = self._tmi_base_urls[0]
        self.username = username
        self._password = password
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            trust_env=False,
            headers={
                "Accept": "application/json",
                "User-Agent": user_agent,
            },
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    def set_password(self, password: str) -> None:
        self._password = password

    async def detect(self) -> GatewayDetection:
        unified = await self._detect_unified()
        if unified.reachable:
            return unified

        nokia = await self._detect_nokia()
        if nokia.reachable:
            return nokia

        return GatewayDetection(
            reachable=False,
            error=unified.error or nokia.error or "Gateway was not detected",
        )

    async def is_reachable(self) -> bool:
        """Mirror HINT Control's broad unified-gateway detection behavior."""
        detection = await self._detect_unified()
        return detection.reachable

    async def _detect_unified(self) -> GatewayDetection:
        errors: list[str] = []
        reachable_error: str | None = None
        for base_url in self._ordered_tmi_base_urls():
            for info_path in self.INFO_PATHS:
                try:
                    response = await self._client.get(_endpoint_url(base_url, info_path))
                except (httpx.HTTPError, OSError) as exc:
                    errors.append(f"{base_url}: {type(exc).__name__}: {exc}")
                    continue

                if not response.is_success:
                    error = (
                        f"{base_url}{info_path}: unified API returned HTTP "
                        f"{response.status_code}"
                    )
                    errors.append(error)
                    if response.status_code not in {403, 404} and reachable_error is None:
                        reachable_error = error
                    continue

                self._active_tmi_base_url = base_url
                device = _extract_mapping(response, "device")
                return GatewayDetection(
                    reachable=True,
                    api_type="unified",
                    supported=True,
                    model=_string_or_none(device.get("model")),
                    manufacturer=_string_or_none(device.get("manufacturer")),
                    name=_string_or_none(device.get("friendlyName") or device.get("name")),
                    error=None,
                )

        if reachable_error:
            return GatewayDetection(
                reachable=True,
                api_type="unified",
                supported=True,
                error=reachable_error,
            )

        return GatewayDetection(
            reachable=False,
            api_type="unified",
            supported=True,
            error=_summarize_errors(errors, "Unified API was not reachable"),
        )

    async def _detect_nokia(self) -> GatewayDetection:
        try:
            response = await self._client.get(self._gateway_root_url() + self.NOKIA_STATUS_PATH)
        except (httpx.HTTPError, OSError) as exc:
            return GatewayDetection(
                reachable=False,
                api_type="nokia",
                supported=False,
                error=f"{type(exc).__name__}: {exc}",
            )

        if not response.is_success:
            return GatewayDetection(
                reachable=False,
                api_type="nokia",
                supported=False,
                error=f"Nokia API returned HTTP {response.status_code}",
            )

        model = "Nokia 5G21"
        manufacturer = "Nokia"
        name = None
        try:
            info_response = await self._client.get(self._gateway_root_url() + self.NOKIA_INFO_PATH)
            app_status = _extract_first_mapping(info_response, "device_app_status")
            model = _string_or_none(app_status.get("ProductClass")) or model
            manufacturer = _string_or_none(app_status.get("ManufacturerOUI")) or manufacturer
            name = _string_or_none(app_status.get("Description"))
        except (httpx.HTTPError, OSError):
            pass

        return GatewayDetection(
            reachable=True,
            api_type="nokia",
            supported=False,
            model=model,
            manufacturer=manufacturer,
            name=name,
            error="Nokia gateway detected; reboot support is not implemented",
        )

    def _gateway_root_url(self) -> str:
        parsed = urlparse(self.base_url)
        if not parsed.scheme or not parsed.hostname:
            return self.base_url.split("/TMI/v1", 1)[0].rstrip("/")
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{parsed.scheme}://{host}"

    async def authenticate(self) -> str:
        if not self._password:
            raise GatewayAuthenticationError("Gateway password is not configured")

        errors: list[str] = []
        auth_problem = False
        for base_url in self._ordered_tmi_base_urls():
            try:
                response = await self._client.post(
                    _endpoint_url(base_url, self.AUTH_PATH),
                    json={"username": self.username, "password": self._password},
                    headers={"Content-Type": "application/json"},
                )
            except (httpx.HTTPError, OSError) as exc:
                errors.append(f"{base_url}: {type(exc).__name__}: {exc}")
                continue

            if not response.is_success:
                auth_problem = True
                errors.append(f"{base_url}: login returned HTTP {response.status_code}")
                continue

            try:
                payload: dict[str, Any] = response.json()
            except ValueError:
                auth_problem = True
                errors.append(f"{base_url}: login response was not valid JSON")
                continue

            auth = payload.get("auth")
            token = auth.get("token") if isinstance(auth, dict) else None
            if isinstance(token, str) and token:
                self._active_tmi_base_url = base_url
                return token

            result = payload.get("result")
            message = result.get("message") if isinstance(result, dict) else None
            safe_message = message if isinstance(message, str) else "No token returned"
            auth_problem = True
            errors.append(f"{base_url}: {safe_message}")

        if errors:
            message = _summarize_errors(errors, "Gateway login failed")
            if auth_problem:
                raise GatewayAuthenticationError(message)
            raise GatewayUnavailableError(
                f"Could not reach the gateway login API: {message}"
            )

        raise GatewayUnavailableError("Could not reach the gateway login API")

    async def reboot(self) -> RebootResult:
        token = await self.authenticate()
        try:
            response = await self._client.post(
                _endpoint_url(self._active_tmi_base_url, self.REBOOT_PATH),
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.is_success:
                return RebootResult(
                    accepted=True,
                    message=f"Gateway accepted reboot request (HTTP {response.status_code})",
                )
            raise GatewayError(f"Gateway reboot failed with HTTP {response.status_code}")
        except (httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            # Some firmware drops the HTTP connection immediately while rebooting.
            logger.warning(
                "Gateway connection ended during reboot request; treating as uncertain acceptance: %s",
                type(exc).__name__,
            )
            return RebootResult(
                accepted=True,
                uncertain=True,
                message=(
                    "Gateway disconnected during the reboot request. The command may have "
                    "been accepted, so the watchdog entered reboot grace to avoid a loop."
                ),
            )
        except (httpx.ConnectError, OSError) as exc:
            raise GatewayUnavailableError(
                f"Could not connect to the gateway reboot API: {type(exc).__name__}"
            ) from exc

    def _ordered_tmi_base_urls(self) -> tuple[str, ...]:
        return (
            self._active_tmi_base_url,
            *(url for url in self._tmi_base_urls if url != self._active_tmi_base_url),
        )


def _endpoint_url(base_url: str, path: str) -> str:
    return f"{base_url}{path}"


def _candidate_tmi_base_urls(base_url: str) -> tuple[str, ...]:
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.hostname:
        return (normalized,)

    path = parsed.path.rstrip("/") or "/TMI/v1"
    ports: list[int | None] = [parsed.port]
    if parsed.scheme == "http":
        # G5AR firmware exposes TMI v1 on plain HTTP port 80, while several
        # other TMHI gateways expose the same API on 8080.
        ports.extend([None, 8080])

    candidates: list[str] = []
    for port in ports:
        candidate = _format_base_url(parsed.scheme, parsed.hostname, port, path)
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _format_base_url(
    scheme: str,
    hostname: str,
    port: int | None,
    path: str,
) -> str:
    host = hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    return f"{scheme}://{netloc}{path}"


def _summarize_errors(errors: list[str], fallback: str) -> str:
    if not errors:
        return fallback
    summary = "; ".join(errors[:3])
    if len(errors) > 3:
        summary = f"{summary}; {len(errors) - 3} more attempts failed"
    return summary


def _extract_mapping(response: httpx.Response, key: str) -> dict[str, Any]:
    if not response.is_success:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _extract_first_mapping(response: httpx.Response, key: str) -> dict[str, Any]:
    if not response.is_success:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
