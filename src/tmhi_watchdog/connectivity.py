from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable

import httpx

from .models import ConnectivityResult, ProbeResult, utc_now


Validator = Callable[[httpx.Response], bool]


@dataclass(frozen=True, slots=True)
class ProbeDefinition:
    url: str
    validator: Validator


def _default_validator(response: httpx.Response) -> bool:
    return 200 <= response.status_code < 400


def _validator_for_url(url: str) -> Validator:
    if "connectivitycheck.gstatic.com/generate_204" in url:
        return lambda response: response.status_code == 204
    if "cloudflare.com/cdn-cgi/trace" in url:
        return lambda response: response.status_code == 200 and "fl=" in response.text
    if "msftconnecttest.com/connecttest.txt" in url:
        return lambda response: (
            response.status_code == 200 and "Microsoft Connect Test" in response.text
        )
    if "captive.apple.com/hotspot-detect.html" in url:
        return lambda response: response.status_code == 200 and "Success" in response.text
    return _default_validator


class ConnectivityChecker:
    def __init__(
        self,
        urls: tuple[str, ...],
        timeout_seconds: float,
        minimum_successes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._probes = [ProbeDefinition(url, _validator_for_url(url)) for url in urls]
        self._minimum_successes = minimum_successes
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            trust_env=False,
            headers={
                "User-Agent": "tmhi-watchdog/0.1",
                "Cache-Control": "no-cache",
            },
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _run_probe(self, probe: ProbeDefinition) -> ProbeResult:
        started = time.perf_counter()
        try:
            response = await self._client.get(probe.url)
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            success = probe.validator(response)
            return ProbeResult(
                url=probe.url,
                success=success,
                latency_ms=latency_ms,
                status_code=response.status_code,
                error=None if success else "Unexpected connectivity-check response",
            )
        except (httpx.HTTPError, OSError) as exc:
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            return ProbeResult(
                url=probe.url,
                success=False,
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def check(self) -> ConnectivityResult:
        results = await asyncio.gather(*(self._run_probe(probe) for probe in self._probes))
        successes = sum(item.success for item in results)
        return ConnectivityResult(
            online=successes >= self._minimum_successes,
            checked_at=utc_now(),
            successful_probes=successes,
            required_successes=self._minimum_successes,
            probes=list(results),
        )
