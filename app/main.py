from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings
from .connectivity import ConnectivityChecker
from .gateway import UnifiedGatewayClient
from .storage import EventStore
from .watchdog import Watchdog


settings = Settings.from_env()
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

store = EventStore(settings.database_path)
checker = ConnectivityChecker(
    settings.probe_urls,
    settings.probe_timeout_seconds,
    settings.minimum_successful_probes,
)
gateway = UnifiedGatewayClient(
    settings.gateway_base_url,
    settings.gateway_username,
    settings.gateway_password,
    settings.gateway_timeout_seconds,
    settings.gateway_user_agent,
)
watchdog = Watchdog(settings, checker, gateway, store)
watchdog_task: asyncio.Task[None] | None = None
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    global watchdog_task
    await store.initialize()
    watchdog_task = asyncio.create_task(watchdog.run(), name="tmhi-watchdog")
    try:
        yield
    finally:
        await watchdog.stop()
        if watchdog_task:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass
        await checker.close()
        await gateway.close()


app = FastAPI(
    title="TMHI Gateway Watchdog",
    version=__version__,
    description="Local internet watchdog and T-Mobile gateway reboot service.",
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Token"],
    )


class RebootRequest(BaseModel):
    force: bool = False


class CheckSeriesRequest(BaseModel):
    count: int = Field(default=3, ge=1, le=30)
    interval_seconds: float = Field(default=5.0, ge=0.0, le=300.0)


def require_api_token(
    x_api_token: Annotated[str | None, Header(alias="X-API-Token")] = None,
) -> None:
    if not settings.api_token:
        raise HTTPException(
            status_code=503,
            detail="Manual control API is disabled until API_TOKEN is configured",
        )
    if x_api_token is None or not secrets.compare_digest(x_api_token, settings.api_token):
        raise HTTPException(status_code=401, detail="Invalid API token")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"ok": True, "version": __version__}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return await watchdog.status_snapshot()


@app.get("/api/config")
async def config() -> dict[str, Any]:
    return settings.safe_summary()


@app.get("/api/events")
async def events(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return await store.recent(limit)


@app.post("/api/check", dependencies=[Depends(require_api_token)])
async def check_now() -> dict[str, Any]:
    return await watchdog.check_once(allow_reboot=False)


@app.post("/api/check/series", dependencies=[Depends(require_api_token)])
async def check_series(request: CheckSeriesRequest) -> dict[str, Any]:
    return await watchdog.check_series(
        count=request.count,
        interval_seconds=request.interval_seconds,
    )


@app.post("/api/gateway/test", dependencies=[Depends(require_api_token)])
async def gateway_test() -> dict[str, Any]:
    try:
        return await watchdog.test_gateway_login()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/reboot", dependencies=[Depends(require_api_token)])
async def reboot(request: RebootRequest) -> dict[str, Any]:
    try:
        return await watchdog.manual_reboot(force=request.force)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Manual reboot failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
