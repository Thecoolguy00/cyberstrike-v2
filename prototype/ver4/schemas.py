"""V4-owned discovery and planner contracts."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class Capability(str, Enum):
    NETWORK = "network"
    HTTP = "http"
    CONTENT = "content"
    HTML = "html"
    JAVASCRIPT = "javascript"
    TECHNOLOGY = "technology"


class DiscoveryStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class DiscoveryBudget(BaseModel):
    max_http_requests: int = 40
    max_js_files: int = 10
    max_body_size: int = 50_000
    max_runtime: int = 180
    max_redirects: int = 5
    max_ferox_hits: int = 50

    @field_validator("max_http_requests", "max_js_files", "max_body_size", "max_runtime", "max_redirects", "max_ferox_hits")
    @classmethod
    def non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("budget values must be non-negative")
        return value


class Observation(BaseModel):
    capability: Capability
    target: str
    evidence: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: DiscoveryStatus = DiscoveryStatus.SUCCESS
    error: Optional[str] = None
    raw_output: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class HTTPObservation(BaseModel):
    method: str
    requested_url: str
    final_url: str = ""
    status: Optional[int] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    cookies: Dict[str, str] = Field(default_factory=dict)
    redirects: List[str] = Field(default_factory=list)
    content_type: str = ""
    body: str = ""
    body_truncated: bool = False
    title: str = ""
    tls_verified: Optional[bool] = None
    tls_warning: Optional[str] = None
    error: Optional[str] = None


class Technology(BaseModel):
    name: str
    category: str
    version: Optional[str] = None
    confidence: float = 1.0
    evidence: List[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class Endpoint(BaseModel):
    url: str
    methods: List[str] = Field(default_factory=lambda: ["GET"])
    status: Optional[int] = None
    source: str = ""


class InputPoint(BaseModel):
    url: str
    param: str
    method: str = "GET"
    input_type: str = ""
    source: str = ""


class ContentHit(BaseModel):
    url: str
    status: Optional[int] = None
    size: Optional[int] = None
    source: str = "feroxbuster"


class DiscoveryKnowledge(BaseModel):
    target: str
    observations: List[Observation] = Field(default_factory=list)
    http_observations: List[HTTPObservation] = Field(default_factory=list)
    ports: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    services: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    endpoints: Dict[str, Endpoint] = Field(default_factory=dict)
    inputs: Dict[str, InputPoint] = Field(default_factory=dict)
    scripts: List[str] = Field(default_factory=list)
    technologies: Dict[str, Technology] = Field(default_factory=dict)
    content_hits: Dict[str, ContentHit] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)
    coverage: Dict[str, Dict[str, Dict[str, bool]]] = Field(default_factory=dict)


class PlannerInput(BaseModel):
    """Stable planner handoff, independent of the legacy state naming."""

    target: str
    knowledge: Dict[str, Any] = Field(default_factory=dict)
    observations: List[Observation] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


def observation_error(capability: Capability, target: str, error: str, raw_output: Optional[str] = None) -> Observation:
    return Observation(
        capability=capability,
        target=target,
        status=DiscoveryStatus.FAILED,
        error=error,
        raw_output=raw_output,
    )
