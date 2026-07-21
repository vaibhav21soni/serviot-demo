import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import JSONResponse

from app import crud, db
from app.config import get_settings
from app.models import (
    Device,
    DeviceCreate,
    DeviceUpdate,
    HealthResponse,
)

logging.basicConfig(level=logging.INFO)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.open_pool()
    await db.run_migrations()
    yield
    await db.close_pool()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health(response: Response):
    """Liveness + readiness in one probe.

    App is up if this handler runs at all. DB is checked with SELECT 1 through
    the pool. Overall status is healthy only if both are up; otherwise 503 so
    load balancers and orchestrators drain the instance.
    """
    db_up = await db.check_db()
    payload = {
        "status": "healthy" if db_up else "unhealthy",
        "app": {"status": "up"},
        "database": {"status": "up" if db_up else "down"},
    }
    if not db_up:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload


@app.get("/devices", response_model=list[Device], tags=["devices"])
async def list_devices():
    return await crud.list_devices()


@app.post(
    "/devices",
    response_model=Device,
    status_code=status.HTTP_201_CREATED,
    tags=["devices"],
)
async def create_device(payload: DeviceCreate):
    return await crud.create_device(payload)


@app.get("/devices/{device_id}", response_model=Device, tags=["devices"])
async def get_device(device_id: int):
    row = await crud.get_device(device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return row


@app.put("/devices/{device_id}", response_model=Device, tags=["devices"])
async def update_device(device_id: int, payload: DeviceUpdate):
    row = await crud.update_device(device_id, payload)
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return row


@app.delete(
    "/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["devices"],
)
async def delete_device(device_id: int):
    ok = await crud.delete_device(device_id)
    if not ok:
        raise HTTPException(status_code=404, detail="device not found")
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)


@app.get("/", tags=["ops"])
async def root():
    return {"service": settings.app_name, "docs": "/docs", "health": "/health"}
