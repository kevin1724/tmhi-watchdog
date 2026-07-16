from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import RebootResult


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

    async def is_reachable(self) -> bool:
        """Mirror HINT Control's broad unified-gateway detection behavior."""
        try:
            response = await self._client.get(self.INFO_PATH)
            return response.status_code not in {403, 404}
        except (httpx.HTTPError, OSError):
            return False

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
