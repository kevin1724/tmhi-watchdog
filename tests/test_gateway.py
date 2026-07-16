import httpx
import pytest

from tmhi_watchdog.gateway import GatewayAuthenticationError, UnifiedGatewayClient


@pytest.mark.asyncio
async def test_authenticate_and_reboot() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"auth": {"token": "abc123"}})
        if request.url.path.endswith("/gateway/reset"):
            assert request.headers["Authorization"] == "Bearer abc123"
            assert request.url.params["set"] == "reboot"
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"device": {"model": "TMOG4AR"}})

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.reboot()
        assert result.accepted is True
        assert result.uncertain is False
        assert len(requests) == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_missing_token_is_auth_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"message": "Bad credentials"}})

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "wrong",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(GatewayAuthenticationError, match="Bad credentials"):
            await client.authenticate()
    finally:
        await client.close()
