from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DeviceStatus(str, Enum):
    online = "online"
    offline = "offline"
    maintenance = "maintenance"


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(min_length=1, max_length=60)
    status: DeviceStatus = DeviceStatus.offline


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: str | None = Field(default=None, min_length=1, max_length=60)
    status: DeviceStatus | None = None


class Device(BaseModel):
    id: int
    name: str
    type: str
    status: DeviceStatus
    created_at: datetime
    updated_at: datetime


class HealthComponent(BaseModel):
    status: str  # "up" | "down"


class HealthResponse(BaseModel):
    status: str  # "healthy" | "unhealthy"
    app: HealthComponent
    database: HealthComponent
