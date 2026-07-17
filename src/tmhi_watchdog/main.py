from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings
from .connectivity import ConnectivityChecker
from .credentials import ManagedEnvFile
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
managed_env = ManagedEnvFile(settings.managed_env_path)
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
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )


class RebootRequest(BaseModel):
    force: bool = False


class CheckSeriesRequest(BaseModel):
    count: int = Field(default=3, ge=1, le=30)
    interval_seconds: float = Field(default=5.0, ge=0.0, le=300.0)


class GatewayTestRequest(BaseModel):
    gateway_password: str = Field(default="", max_length=512, repr=False)


class GatewayLoginRequest(BaseModel):
    gateway_password: str = Field(..., min_length=1, max_length=512, repr=False)
    remember: bool = True


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


@app.post("/api/check")
async def check_now() -> dict[str, Any]:
    return await watchdog.check_once(allow_reboot=False)


@app.post("/api/check/series")
async def check_series(request: CheckSeriesRequest) -> dict[str, Any]:
    return await watchdog.check_series(
        count=request.count,
        interval_seconds=request.interval_seconds,
    )


@app.post("/api/gateway/test")
async def gateway_test(request: GatewayTestRequest | None = None) -> dict[str, Any]:
    try:
        supplied_password = request.gateway_password if request else ""
        if supplied_password:
            test_gateway = UnifiedGatewayClient(
                settings.gateway_base_url,
                settings.gateway_username,
                supplied_password,
                settings.gateway_timeout_seconds,
                settings.gateway_user_agent,
            )
            try:
                reachable = await test_gateway.is_reachable()
                if not reachable:
                    return {
                        "reachable": False,
                        "authenticated": False,
                        "used_supplied_password": True,
                    }
                await test_gateway.authenticate()
                return {
                    "reachable": True,
                    "authenticated": True,
                    "used_supplied_password": True,
                }
            finally:
                await test_gateway.close()
        return await watchdog.test_gateway_login()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/gateway/login")
async def gateway_login(request: GatewayLoginRequest) -> dict[str, Any]:
    test_gateway = UnifiedGatewayClient(
        settings.gateway_base_url,
        settings.gateway_username,
        request.gateway_password,
        settings.gateway_timeout_seconds,
        settings.gateway_user_agent,
    )
    try:
        reachable = await test_gateway.is_reachable()
        if not reachable:
            return {
                "reachable": False,
                "authenticated": False,
                "saved": False,
                "gateway_password_configured": bool(settings.gateway_password),
                "gateway_password_source": settings.gateway_password_source,
            }
        await test_gateway.authenticate()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await test_gateway.close()

    if request.remember:
        try:
            managed_env.set_value("GATEWAY_PASSWORD", request.gateway_password)
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail="Gateway login worked, but the password could not be saved",
            ) from exc
        password_source = "saved"
    else:
        password_source = "runtime"

    settings.gateway_password = request.gateway_password
    settings.gateway_password_source = password_source
    gateway.set_password(request.gateway_password)
    await store.record(
        "gateway_login_saved" if request.remember else "gateway_login_authenticated",
        (
            "Gateway login saved from dashboard"
            if request.remember
            else "Gateway login authenticated from dashboard"
        ),
        {"username": settings.gateway_username, "remember": request.remember},
    )
    return {
        "reachable": True,
        "authenticated": True,
        "saved": request.remember,
        "gateway_password_configured": True,
        "gateway_password_source": password_source,
    }


@app.delete("/api/gateway/login")
async def gateway_login_clear() -> dict[str, Any]:
    try:
        saved_removed = managed_env.clear_value("GATEWAY_PASSWORD")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Saved gateway login could not be cleared",
        ) from exc
    environment_password_active = settings.gateway_password_source == "environment"

    if not environment_password_active:
        settings.gateway_password = ""
        settings.gateway_password_source = "none"
        gateway.set_password("")

    await store.record(
        "gateway_login_cleared",
        "Saved gateway login cleared from dashboard",
        {
            "saved_removed": saved_removed,
            "environment_password_active": environment_password_active,
        },
    )
    return {
        "cleared": saved_removed or not environment_password_active,
        "saved_removed": saved_removed,
        "gateway_password_configured": bool(settings.gateway_password),
        "gateway_password_source": settings.gateway_password_source,
    }


@app.post("/api/reboot")
async def reboot(request: RebootRequest) -> dict[str, Any]:
    try:
        return await watchdog.manual_reboot(force=request.force)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Manual reboot failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
