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
async def test_reboot_g5ar_on_http_port_80_fallback() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.port == 8080:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"auth": {"token": "g5ar-token"}})
        if request.url.path.endswith("/gateway/reset"):
            assert request.headers["Authorization"] == "Bearer g5ar-token"
            assert request.url.params["set"] == "reboot"
            return httpx.Response(200, json={})
        return httpx.Response(404)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.reboot()
    finally:
        await client.close()

    assert result.accepted is True
    assert result.uncertain is False
    successful_paths = [
        request.url.path for request in requests if request.url.port != 8080
    ]
    assert successful_paths == [
        "/TMI/v1/auth/login",
        "/TMI/v1/gateway/reset",
    ]


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


@pytest.mark.asyncio
async def test_detect_unified_gateway_model() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/TMI/v1/gateway/")
        return httpx.Response(
            200,
            json={
                "device": {
                    "manufacturer": "Arcadyan",
                    "model": "TMOG4AR",
                    "friendlyName": "T-Mobile Gateway",
                }
            },
        )

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        detection = await client.detect()
    finally:
        await client.close()

    assert detection.reachable is True
    assert detection.supported is True
    assert detection.api_type == "unified"
    assert detection.model == "TMOG4AR"
    assert detection.manufacturer == "Arcadyan"


@pytest.mark.asyncio
async def test_detect_g5ar_on_http_port_80_gateway_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 8080:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path.endswith("/TMI/v1/gateway/"):
            return httpx.Response(404)
        if request.url.path.endswith("/TMI/v1/gateway"):
            assert request.url.params["get"] == "all"
            return httpx.Response(
                200,
                json={
                    "device": {
                        "manufacturer": "Arcadyan",
                        "model": "TMO-G5AR",
                        "name": "T-Mobile 5G Gateway",
                    }
                },
            )
        return httpx.Response(404)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        detection = await client.detect()
    finally:
        await client.close()

    assert detection.reachable is True
    assert detection.supported is True
    assert detection.api_type == "unified"
    assert detection.model == "TMO-G5AR"
    assert detection.manufacturer == "Arcadyan"


@pytest.mark.asyncio
async def test_detect_nokia_gateway_as_unsupported() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(("/TMI/v1/gateway/", "/TMI/v1/gateway")):
            return httpx.Response(404)
        if request.url.path.endswith("/dashboard_device_status_web_app.cgi"):
            return httpx.Response(200, json={"num_extenders": 0})
        if request.url.path.endswith("/dashboard_device_info_status_web_app.cgi"):
            return httpx.Response(
                200,
                json={
                    "device_app_status": [
                        {
                            "ManufacturerOUI": "Nokia",
                            "ProductClass": "5G21",
                            "Description": "Nokia FastMile",
                        }
                    ]
                },
            )
        return httpx.Response(500)

    client = UnifiedGatewayClient(
        "http://192.168.12.1:8080/TMI/v1",
        "admin",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        detection = await client.detect()
    finally:
        await client.close()

    assert detection.reachable is True
    assert detection.supported is False
    assert detection.api_type == "nokia"
    assert detection.model == "5G21"
