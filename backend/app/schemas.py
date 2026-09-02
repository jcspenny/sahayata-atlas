from typing import Optional, Literal
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str
    time: str


class LocationOut(BaseModel):
    query_type: Literal["city", "coordinates"]
    display_name: str
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    country_code: str
    latitude: float
    longitude: float


class Coverage(BaseModel):
    radius_metres: int
    healthcare_status: Literal["available", "partial", "unavailable"]
    is_partial: bool
    warnings: list[str] = Field(default_factory=list)


class Organisation(BaseModel):
    type: Literal["government", "private", "public_sector", "unclassified"]
    name: Optional[str] = None
    inferred: bool


class Source(BaseModel):
    name: str
    record_id: Optional[str] = None
    record_url: Optional[str] = None
    updated_at: Optional[str] = None


class Resource(BaseModel):
    id: str
    name: str
    category: Literal["medical", "shelter", "security", "general"]
    facility_type: Literal["hospital", "clinic", "public_place"]
    latitude: float
    longitude: float
    distance_metres: Optional[int] = None
    organisation: Organisation
    listing_status: Literal["listed"]
    source: Source


class Meta(BaseModel):
    total: int


class NearbyResponse(BaseModel):
    schema_version: str
    request_id: str
    generated_at: str
    location: LocationOut
    coverage: Coverage
    resources: list[Resource]
    meta: Meta
