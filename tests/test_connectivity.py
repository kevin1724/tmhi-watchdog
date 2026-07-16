import httpx
import pytest

from app.connectivity import ConnectivityChecker


@pytest.mark.asyncio
async def test_two_successful_probes_means_online() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if "gstatic" in request.url.host:
            return httpx.Response(204)
        if "cloudflare" in request.url.host:
            return httpx.Response(200, text="fl=123\nip=1.2.3.4")
        return httpx.Response(500)

    checker = ConnectivityChecker(
        (
            "https://connectivitycheck.gstatic.com/generate_204",
            "https://www.cloudflare.com/cdn-cgi/trace",
            "http://www.msftconnecttest.com/connecttest.txt",
        ),
        5,
        2,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await checker.check()
        assert result.online is True
        assert result.successful_probes == 2
    finally:
        await checker.close()
