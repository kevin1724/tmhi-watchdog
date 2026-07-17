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
    INFO_PATH = "/gateway/?get=all"
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
        try:
            response = await self._client.get(self.INFO_PATH)
        except (httpx.HTTPError, OSError) as exc:
            return GatewayDetection(
                reachable=False,
                api_type="unified",
                supported=True,
                error=f"{type(exc).__name__}: {exc}",
            )

        if response.status_code in {403, 404}:
            return GatewayDetection(
                reachable=False,
                api_type="unified",
                supported=True,
                error=f"Unified API returned HTTP {response.status_code}",
            )

        device = _extract_mapping(response, "device")
        return GatewayDetection(
            reachable=True,
            api_type="unified",
            supported=True,
            model=_string_or_none(device.get("model")),
            manufacturer=_string_or_none(device.get("manufacturer")),
            name=_string_or_none(device.get("friendlyName") or device.get("name")),
            error=None if response.is_success else f"Unified API returned HTTP {response.status_code}",
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

        try:
            response = await self._client.post(
                self.AUTH_PATH,
                json={"username": self.username, "password": self._password},
                headers={"Content-Type": "application/json"},
            )
        except (httpx.HTTPError, OSError) as exc:
            raise GatewayUnavailableError(
                f"Could not reach the gateway login API: {type(exc).__name__}"
            ) from exc

        if not response.is_success:
            raise GatewayAuthenticationError(
                f"Gateway login failed with HTTP {response.status_code}"
            )

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise GatewayAuthenticationError(
                "Gateway login response was not valid JSON"
            ) from exc

        auth = payload.get("auth")
        token = auth.get("token") if isinstance(auth, dict) else None
        if not isinstance(token, str) or not token:
            result = payload.get("result")
            message = result.get("message") if isinstance(result, dict) else None
            safe_message = message if isinstance(message, str) else "No token returned"
            raise GatewayAuthenticationError(f"Gateway login failed: {safe_message}")
        return token

    async def reboot(self) -> RebootResult:
        token = await self.authenticate()
        try:
            response = await self._client.post(
                self.REBOOT_PATH,
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
