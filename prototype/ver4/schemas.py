"""V4-owned discovery, planner and attack contracts (migrated from sub_agents/schemas.py)."""

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
    max_l2_scan_runtime: int = 900
    max_l2_service_ports_per_batch: int = 5000

    @field_validator(
        "max_http_requests", "max_js_files", "max_body_size", "max_runtime",
        "max_redirects", "max_ferox_hits", "max_l2_scan_runtime",
        "max_l2_service_ports_per_batch",
    )
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


class Finding(BaseModel):
    """A single vuln finding extracted from an attack session."""

    id: str = ""
    type: str = ""
    location: str = ""
    severity: str = "Unknown"
    confirmed: bool = False
    description: str = ""
    evidence: str = ""
    source: str = ""
    # timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExploitIntel(BaseModel):
    """Exploit intelligence for a specific technology/version (from intel_a)."""

    technology: str = ""
    version: str = "unknown"
    location: str = Field(default="", description="host:port or base URL the technology is served on (web-only; empty for non-web services)")
    cve: str = ""
    cvss: float = 0.0
    severity: str = "Unknown"
    poc: bool = False
    description: str = ""
    recommended_tests: List[str] = Field(default_factory=list)
    payloads: List[str] = Field(default_factory=list, description="Exact exploit payloads / PoC commands copied verbatim (the exploit only works with these)")
    tested: bool = False
    sources: List[str] = Field(default_factory=list)


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
    findings: Dict[str, Finding] = Field(default_factory=dict)
    exploit_intelligence: Dict[str, ExploitIntel] = Field(default_factory=dict)
    background_tasks: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
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


# ─── Coverage keys (migrated from sub_agents/schemas.py::CoverageKeys) ───────

class CoverageKeys:
    # Recon (deterministic discovery)
    PORT_SCAN = "port_scan"
    SERVICE_FINGERPRINT = "service_fingerprint"
    DIR_DISCOVERY = "dir_discovery"
    JS_DISCOVERY = "js_discovery"
    API_DISCOVERY = "api_discovery"
    PARAM_DISCOVERY = "param_discovery"
    NETWORK_L2 = "network_l2"

    # Attack analysis
    AUTH_LOGIN = "auth.login_testing"
    IDOR_NUMERIC = "idor.numeric_params"
    DOM_XSS = "xss.dom"


# ─── Tactical task models (migrated from sub_agents/schemas.py) ──────────────

class Task(BaseModel):
    """Single task for an agent within a scoped attack session."""

    agent: str = Field(..., description="Agent name — must be in the allowed list for the attack session")
    task_description: str = Field(..., description="Clear, specific task. MUST start with [vuln_analysis] (the agent-recognized testing phase) and include the scoped target URL/host.")
    task_id: str = Field(..., description="Unique short slug for dependency tracking")
    depends_on: List[str] = Field(default_factory=list)
    coverage_keys: List[str] = Field(default_factory=list)


class TacticalPlan(BaseModel):
    """Output of the migrated tactical planner node."""

    plan: List[Task] = Field(default_factory=list)
    phase_summary: str = Field(
        default="",
        description="Summary of what this attack session achieved — set ONLY when plan is empty (session complete)",
    )


class TacticalExtraction(BaseModel):
    """Output of the migrated tactical extractor node."""

    findings: List[Finding] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


# ─── Decision layer models ────────────────────────────────────────────────────

class DecisionAction(str, Enum):
    NETWORK_L2 = "network_l2"
    ATTACK = "attack"
    REPORT = "report"


class PlannerDecision(BaseModel):
    """Single decision emitted by the Layer-2 decision planner."""

    action: DecisionAction
    target: str = Field(default="", description="Confirmed base URL (scheme://host:port) when action=ATTACK")
    rationale: str = ""


class AttackSession(BaseModel):
    """Record of one scoped vuln/exploit session."""

    target: str = ""
    objective: str = ""
    iterations: int = 0
    executions_consumed: int = 0
    summary: str = ""
    completed: bool = False