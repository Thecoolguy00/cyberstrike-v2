# schemas.py
from typing import Annotated, List, Dict, TypedDict, Optional
import operator
from pydantic import BaseModel, Field
from langgraph.graph import MessagesState

class BaseState(MessagesState):
    tool_used: Annotated[List[str], operator.add]
    task: str
    # Background task info (set by mcp_exec_node, consumed by schedule_callback_node)
    # Structure: {"task_id": str, "tool": str, "started": bool}
    _bg_task_info: Optional[dict]

# ─── Phase definitions ────────────────────────────────────────────────────────

PHASES = ["recon", "enumeration", "vuln_analysis", "exploitation", "reporting"]

PHASE_AGENT_MAP: Dict[str, List[str]] = {
    "recon":         ["nmap_a", "curl_a"],
    "enumeration":   ["ferox_a", "curl_a"],
    "vuln_analysis": ["xss_a", "curl_a", "python_a"],
    "exploitation":  ["python_a", "xss_a", "curl_a"],
    "reporting":     [],
}

MAX_PHASE_ITERATIONS = 8

# ─── Knowledge graph ──────────────────────────────────────────────────────────

class OpenPort(TypedDict, total=False):
    port: int
    service: str
    version: str
    state: str

class WebService(TypedDict, total=False):
    url: str
    port: int
    tech_stack: List[str]
    headers: Dict[str, str]
    title: str

class InputPoint(TypedDict, total=False):
    url: str
    param: str
    method: str
    context: str

class Finding(TypedDict, total=False):
    type: str
    location: str
    severity: str           # fixed typo: was "serverity"
    confirmed: bool
    description: str

class TargetKnowledge(TypedDict, total=False):
    open_ports:   List[OpenPort]
    web_services: List[WebService]
    endpoints:    List[str]
    input_points: List[InputPoint]
    findings:     List[Finding]
    notes:        List[str]


def void_knowledge() -> TargetKnowledge:
    return TargetKnowledge(
        open_ports=[],
        web_services=[],
        endpoints=[],
        input_points=[],
        findings=[],
        notes=[],
    )


def merge_knowledge(base: TargetKnowledge, update: TargetKnowledge) -> TargetKnowledge:
    """Merge update into base with per-field deduplication."""
    if not update:
        return base

    merged: TargetKnowledge = {
        "open_ports":   list(base.get("open_ports",   [])),
        "web_services": list(base.get("web_services", [])),
        "endpoints":    list(base.get("endpoints",    [])),
        "input_points": list(base.get("input_points", [])),
        "findings":     list(base.get("findings",     [])),
        "notes":        list(base.get("notes",        [])),
    }

    existing_ports = {p.get("port") for p in merged["open_ports"]}
    for p in update.get("open_ports", []) or []:
        if p.get("port") not in existing_ports:
            merged["open_ports"].append(p)
            existing_ports.add(p.get("port"))

    existing_urls = {s.get("url") for s in merged["web_services"]}
    for s in update.get("web_services", []) or []:
        if s.get("url") not in existing_urls:
            merged["web_services"].append(s)
            existing_urls.add(s.get("url"))
        else:
            for existing in merged["web_services"]:
                if existing.get("url") == s.get("url"):
                    existing_stack = set(existing.get("tech_stack", []) or [])
                    existing_stack.update(s.get("tech_stack", []) or [])
                    existing["tech_stack"] = list(existing_stack)
                    existing.setdefault("headers", {}).update(s.get("headers", {}) or {})

    existing_endpoints = set(merged["endpoints"])
    for e in update.get("endpoints", []) or []:
        if e not in existing_endpoints:
            merged["endpoints"].append(e)
            existing_endpoints.add(e)

    existing_inputs = {
        (ip.get("url"), ip.get("param"), ip.get("method"))
        for ip in merged["input_points"]
    }
    for ip in update.get("input_points", []) or []:
        key = (ip.get("url"), ip.get("param"), ip.get("method"))
        if key not in existing_inputs:
            merged["input_points"].append(ip)
            existing_inputs.add(key)

    existing_findings = {
        (f.get("type"), f.get("location")) for f in merged["findings"]
    }
    for f in update.get("findings", []) or []:
        key = (f.get("type"), f.get("location"))
        if key not in existing_findings:
            merged["findings"].append(f)
            existing_findings.add(key)
        else:
            for existing in merged["findings"]:
                if (existing.get("type"), existing.get("location")) == key:
                    if f.get("confirmed"):
                        existing["confirmed"] = True
                    if f.get("description"):
                        existing["description"] = f.get("description")

    existing_notes = set(merged["notes"])
    for n in update.get("notes", []) or []:
        if n not in existing_notes:
            merged["notes"].append(n)
            existing_notes.add(n)

    return merged


def _merge_str_lists(left: Optional[List[str]], right: Optional[List[str]]) -> List[str]:
    if left is None:
        left = []
    if right is None:
        right = []
    seen = list(left)
    for item in right:
        if item not in seen:
            seen.append(item)
    return seen


# ─── Vuln advisor schemas ─────────────────────────────────────────────────────

class VulnNudge(BaseModel):
    """
    Lightweight directive the advisor emits EVERY cycle across ALL phases.

    priority controls how strongly the tactical planner must follow it:
      - "high"   : address this before anything else this cycle
      - "medium" : consider this after current plan items
      - "skip"   : nothing actionable right now — tactical follows its own flow
    """
    vuln_id:          str       = Field("",  description="Unique slug e.g. 'reflected_xss', 'git_exposure'")
    label:            str       = Field("",  description="Human-readable label e.g. 'Reflected XSS'")
    priority:         str       = Field("skip", description="'high' | 'medium' | 'skip'")
    rationale:        str       = Field("",  description="What in the knowledge graph triggered this nudge")
    specific_targets: List[str] = Field(default_factory=list, description="Concrete URLs/params/endpoints from the knowledge graph")
    suggested_agents: List[str] = Field(default_factory=list, description="Agents suited to probe this — must be subset of phase agents")
    skip_reason:      str       = Field("",  description="Populated only when priority='skip'")


# Keep VulnFocus as an alias so existing imports in master_graph don't break
VulnFocus = VulnNudge


# ─── Master state ─────────────────────────────────────────────────────────────

class PhaseHistoryRecord(TypedDict):
    phase:               str
    summary:             str
    iterations:          int
    executions_consumed: int


class MasterState(TypedDict, total=False):
    query: str

    # phase tracking
    current_phase:         str
    phase_objective:       str
    phase_iteration_count: int

    # knowledge
    knowledge: TargetKnowledge

    # execution
    plan:              List[dict]
    execution_history: List[Dict[str, str]]
    phase_history:     List[PhaseHistoryRecord]

    # tactical → strategic handoff
    _phase_summary:       str
    _extracted_knowledge: TargetKnowledge

    # advisor handoff — refreshed every cycle, all phases
    vuln_nudge:    Optional[VulnNudge]                       # current nudge from advisor
    checked_vulns: Annotated[List[str], _merge_str_lists]    # persists entire pentest

    # output
    final_answer: str
    thinking:     str


# ─── Tactical planner schemas ─────────────────────────────────────────────────

class Task(BaseModel):
    """Single task for an agent."""
    agent:            str       = Field(..., description="Agent name — must be in the allowed list for this phase")
    task_description: str       = Field(..., description="Clear, specific task instruction")
    task_id:          str       = Field(..., description="Unique short slug e.g. 'nmap_basic', 'curl_headers'. Used for dependency tracking.")
    depends_on:       List[str] = Field(default_factory=list, description="List of task_ids that must complete before this task runs. Empty = can run immediately in parallel.")


class TacticalPlan(BaseModel):
    """Output of the tactical planner for a single phase cycle."""
    plan: List[Task] = Field(
        default_factory=list,
        description=(
            "Batch of tasks for this cycle. Tag independent tasks with empty depends_on "
            "so they run in parallel. Use depends_on to express real ordering constraints."
        )
    )
    phase_summary: str = Field(
        default="",
        description="Summary of this phase's findings — set ONLY when plan is empty (phase complete)"
    )
    extracted_knowledge: TargetKnowledge = Field(
        default_factory=void_knowledge,
        description="Structured findings from this cycle's execution results — always populate what you can"
    )
    thinking: str = Field(..., description="Reasoning for the current plan/decision")


# ─── Strategic planner schemas ────────────────────────────────────────────────

class PhaseDecision(BaseModel):
    """Output of the strategic planner."""
    current_phase:   str = Field(..., description=f"One of: {', '.join(PHASES)}")
    phase_objective: str = Field(..., description="Specific, scoped objective for the tactical planner this phase")
    final_answer:    str = Field(default="", description="Set ONLY when entire pentest is complete")
    thinking:        str = Field(..., description="Reasoning for this phase decision")