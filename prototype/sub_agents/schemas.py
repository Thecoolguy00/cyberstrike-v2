# schemas.py
from typing import Annotated, List, Dict, TypedDict, Optional
import operator
from pydantic import BaseModel, Field
from langgraph.graph import MessagesState

class BaseState(MessagesState):
    tool_used: Annotated[List[str], operator.add]
    task: str

# ─── Phase definitions ────────────────────────────────────────────────────────

PHASES = ["recon", "attack_analysis", "reporting"]

PHASE_AGENT_MAP: Dict[str, List[str]] = {
    "recon":         ["nmap_a", "http_a"],
    "attack_analysis": ["nmap_a", "http_a", "ferox_a", "python_a", "xss_a"],
    "reporting":     [],
    "network":       ["nmap_a"],
    "http":          ["http_a", "ferox_a"],
}

class CoverageKeys:
    # Recon checks
    PORT_SCAN = "port_scan"
    SERVICE_FINGERPRINT = "service_fingerprint"
    DIR_DISCOVERY = "dir_discovery"
    JS_DISCOVERY = "js_discovery"
    API_DISCOVERY = "api_discovery"
    PARAM_DISCOVERY = "param_discovery"
    
    # Attack Analysis checks
    AUTH_LOGIN = "auth.login_testing"
    IDOR_NUMERIC = "idor.numeric_params"
    DOM_XSS = "xss.dom"

MAX_PHASE_ITERATIONS = 8

# ─── Knowledge graph ──────────────────────────────────────────────────────────

class OpenPort(TypedDict, total=False):
    port: Optional[int]
    service: Optional[str]
    version: Optional[str]
    state: Optional[str]

class WebService(TypedDict, total=False):
    url: Optional[str]
    port: Optional[int]
    tech_stack: Optional[List[str]]
    headers: Optional[Dict[str, str]]
    title: Optional[str]

class InputPoint(TypedDict, total=False):
    url: Optional[str]
    param: Optional[str]
    method: Optional[str]
    context: Optional[str]

class Finding(TypedDict, total=False):
    type: Optional[str]
    location: Optional[str]
    severity: Optional[str]
    confirmed: Optional[bool]
    description: Optional[str]


class KnownCVE(TypedDict, total=False):
    """
    A CVE discovered by intel_a during recon/enumeration.
    Carried forward so vuln_analysis knows exactly what to test.
    """
    cve_id:            Optional[str]   # e.g. "CVE-2023-38501"
    technology:        Optional[str]   # e.g. "copyparty"
    version:           Optional[str]   # e.g. "1.8.6" or "unknown"
    severity:          Optional[str]   # Critical/High/Medium/Low/Unknown
    public_exploit:    Optional[bool]
    github_poc:        Optional[bool]
    description:       Optional[str]   # one-line summary from intel report
    recommended_tests: Optional[List[str]]  # actionable test hints from intel report
    tested:            Optional[bool]  # set True by tactical when a test task is dispatched


class TargetKnowledge(TypedDict, total=False):
    # Evolved dict keys
    ports: Dict[str, dict]                 # port_num -> {"service": str, "version": str, "state": str}
    services: Dict[str, dict]              # tech_name -> {"version": str, "port": int}
    endpoints_dict: Dict[str, dict]        # url -> {"methods": List[str], "status": int}
    inputs: Dict[str, dict]                # input_id -> {"url": str, "param": str, "method": str, "type": str}
    exploit_intelligence: Dict[str, dict]  # tech_version -> {"cve": str, "cvss": float, "poc": bool}
    findings_dict: Dict[str, dict]         # finding_id -> {"type": str, "location": str, "severity": str, "confirmed": bool, "description": str}
    background_tasks: Dict[str, dict]      # task_id -> {"status": str, "output": str}
    coverage: Dict[str, dict]              # phase -> check_id -> {"required": bool, "completed": bool}

    # Legacy list keys for backward compatibility
    open_ports:   List[OpenPort]
    web_services: List[WebService]
    endpoints:    List[str]
    input_points: List[InputPoint]
    findings:     List[Finding]
    known_cves:   List[KnownCVE]
    notes:        List[str]


def void_knowledge() -> TargetKnowledge:
    return TargetKnowledge(
        # Evolved dict keys
        ports={},
        services={},
        endpoints_dict={},
        inputs={},
        exploit_intelligence={},
        findings_dict={},
        background_tasks={},
        coverage={
            "recon": {
                # port_scan is always required — it's the entry gate.
                # All other recon checks start as required=False.
                # The tactical_extractor promotes them to required=True
                # only when their prerequisite is met:
                #   service_fingerprint → promoted when open ports found
                #   dir/js/api/param discovery → promoted when HTTP service confirmed
                # This prevents the reviewer from scheduling gobuster/JS/param
                # discovery before nmap has even run.
                CoverageKeys.PORT_SCAN:           {"required": True,  "completed": False},
                CoverageKeys.SERVICE_FINGERPRINT: {"required": False, "completed": False},
                CoverageKeys.DIR_DISCOVERY:       {"required": False, "completed": False},
                CoverageKeys.JS_DISCOVERY:        {"required": False, "completed": False},
                CoverageKeys.API_DISCOVERY:       {"required": False, "completed": False},
                CoverageKeys.PARAM_DISCOVERY:     {"required": False, "completed": False},
            },
            "attack_analysis": {},
            "reporting": {}
        },
        # Legacy list keys
        open_ports=[],
        web_services=[],
        endpoints=[],
        input_points=[],
        findings=[],
        known_cves=[],
        notes=[],
    )


def _sync_knowledge_legacy(kb: TargetKnowledge) -> TargetKnowledge:
    """Sync new dict keys to legacy list keys for backward compatibility."""
    kb["open_ports"] = [
        {"port": int(p_num), "service": val.get("service", ""), "version": val.get("version", ""), "state": val.get("state", "open")}
        for p_num, val in kb.get("ports", {}).items()
    ]
    kb["web_services"] = [
        {
            "url": val.get("url", f"http://localhost:{val.get('port', 80)}"),
            "port": val.get("port", 80),
            "tech_stack": val.get("tech_stack", []),
            "headers": val.get("headers", {}),
            "title": val.get("title", "")
        }
        for s_name, val in kb.get("services", {}).items()
    ]
    # Update endpoints as list of keys
    kb["endpoints"] = list(kb.get("endpoints_dict", {}).keys())
    
    kb["input_points"] = [
        {
            "url": val.get("url", ""),
            "param": val.get("param", ""),
            "method": val.get("method", "GET"),
            "context": val.get("type", "")
        }
        for i_id, val in kb.get("inputs", {}).items()
    ]
    kb["findings"] = list(kb.get("findings_dict", {}).values())
    kb["known_cves"] = [
        {
            "cve_id": cve_info.get("cve", ""),
            "technology": s_name,
            "version": cve_info.get("version", "unknown"),
            "severity": cve_info.get("severity", "Unknown"),
            "public_exploit": cve_info.get("poc", False),
            "github_poc": cve_info.get("poc", False),
            "description": cve_info.get("description", ""),
            "recommended_tests": cve_info.get("recommended_tests", []),
            "tested": cve_info.get("tested", False)
        }
        for s_name, cve_info in kb.get("exploit_intelligence", {}).items()
    ]
    return kb


def merge_knowledge(base: TargetKnowledge, update: TargetKnowledge) -> TargetKnowledge:
    """Merge update into base with dict updates."""
    if not update:
        return base

    merged: TargetKnowledge = {
        "ports":                dict(base.get("ports", {})),
        "services":             dict(base.get("services", {})),
        "endpoints_dict":       dict(base.get("endpoints_dict", {})),
        "inputs":               dict(base.get("inputs", {})),
        "exploit_intelligence": dict(base.get("exploit_intelligence", {})),
        "findings_dict":        dict(base.get("findings_dict", {})),
        "background_tasks":     dict(base.get("background_tasks", {})),
        "coverage":             {
            "recon":           dict(base.get("coverage", {}).get("recon", {})),
            "attack_analysis": dict(base.get("coverage", {}).get("attack_analysis", {})),
            "reporting":       dict(base.get("coverage", {}).get("reporting", {})),
        },
        "notes":                list(base.get("notes", [])),
    }

    # Standard dict updates for incoming data
    for k in ["ports", "services", "endpoints_dict", "inputs", "exploit_intelligence", "background_tasks"]:
        if val := update.get(k):
            merged[k].update(val)

    # Dedup and append notes
    existing_notes = set(merged["notes"])
    for n in update.get("notes", []) or []:
        if n not in existing_notes:
            merged["notes"].append(n)
            existing_notes.add(n)

    # For findings, merge selectively
    if findings_update := update.get("findings_dict"):
        for f_id, f in findings_update.items():
            if f_id not in merged["findings_dict"]:
                merged["findings_dict"][f_id] = dict(f)
            else:
                existing = merged["findings_dict"][f_id]
                if f.get("confirmed"):
                    existing["confirmed"] = True
                if f.get("description"):
                    existing["description"] = f.get("description")
                if f.get("severity"):
                    existing["severity"] = f.get("severity")

    # Merge coverage
    if coverage_update := update.get("coverage"):
        for phase in ["recon", "attack_analysis", "reporting"]:
            if phase_cov := coverage_update.get(phase):
                for check_id, check_val in phase_cov.items():
                    if check_id not in merged["coverage"][phase]:
                        merged["coverage"][phase][check_id] = dict(check_val)
                    else:
                        if "completed" in check_val:
                            merged["coverage"][phase][check_id]["completed"] = check_val["completed"]
                        if "required" in check_val:
                            merged["coverage"][phase][check_id]["required"] = check_val["required"]

    # Also accept legacy inputs merging if any updates were in legacy format
    for lp in update.get("open_ports", []) or []:
        p_num = str(lp.get("port"))
        if p_num not in merged["ports"]:
            merged["ports"][p_num] = {"service": lp.get("service", ""), "version": lp.get("version", ""), "state": lp.get("state", "open")}
    for ls in update.get("web_services", []) or []:
        # Find technology stack
        stack = ls.get("tech_stack", [])
        tech = stack[0] if stack else "web"
        if tech not in merged["services"]:
            merged["services"][tech] = {"version": "unknown", "port": ls.get("port", 80), "tech_stack": stack, "headers": ls.get("headers", {}), "title": ls.get("title", "")}
    for le in update.get("endpoints", []) or []:
        if le not in merged["endpoints_dict"]:
            merged["endpoints_dict"][le] = {"methods": ["GET"], "status": 200}
    for li in update.get("input_points", []) or []:
        i_id = f"{li.get('url')}_{li.get('param')}_{li.get('method')}"
        if i_id not in merged["inputs"]:
            merged["inputs"][i_id] = {"url": li.get("url"), "param": li.get("param"), "method": li.get("method"), "type": li.get("context", "")}
    for lf in update.get("findings", []) or []:
        f_id = f"{lf.get('type')}_{lf.get('location')}"
        if f_id not in merged["findings_dict"]:
            merged["findings_dict"][f_id] = dict(lf)

    # Sync and return
    return _sync_knowledge_legacy(merged)


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
    last_node:             str

    # knowledge
    knowledge: TargetKnowledge

    # execution
    plan:                   List[dict]
    execution_history:      List[Dict[str, str]]
    last_execution_results: List[Dict[str, str]]  # only the most recent execute batch
    phase_history:          List[PhaseHistoryRecord]

    # tactical → strategic handoff
    _phase_summary:       str
    _extracted_knowledge: TargetKnowledge

    # advisor handoff — refreshed every cycle, all phases
    vuln_nudge:    Optional[VulnNudge]                       # current nudge from advisor
    checked_vulns: Annotated[List[str], _merge_str_lists]    # persists entire pentest

    # output
    final_answer: str

    metrics:      Dict[str, int]


# ─── Tactical schemas ─────────────────────────────────────────────────────────

class Task(BaseModel):
    """Single task for an agent."""
    agent:            str       = Field(..., description="Agent name — must be in the allowed list for this phase")
    task_description: str       = Field(..., description="Clear, specific task instruction. MUST include the current phase name so agents can enforce their own phase lock.")
    task_id:          str       = Field(..., description="Unique short slug e.g. 'nmap_basic', 'curl_headers'. Used for dependency tracking.")
    depends_on:       List[str] = Field(default_factory=list, description="List of task_ids that must complete before this task runs. Empty = can run immediately in parallel.")
    coverage_keys:    List[str] = Field(default_factory=list, description="The specific coverage matrix keys this task satisfies. e.g. ['port_scan', 'service_fingerprint']")


class TacticalExtraction(BaseModel):
    """
    Output of the tactical_extractor node.
    Reads the last execution batch and pulls out ONLY NEW structured findings —
    things not already in the knowledge graph. No planning.
    """
    extracted_knowledge: TargetKnowledge = Field(
        default_factory=void_knowledge,
        description=(
            "Structured findings extracted from THIS cycle's execution results ONLY. "
            "Do NOT re-copy findings already present in the knowledge graph. "
            "Only include entries that are genuinely new or updated."
        )
    )


class TacticalPlan(BaseModel):
    """
    Output of the tactical_planner node.
    Plans the next task batch only — no extraction (that is done by tactical_extractor).
    """
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


# ─── Strategic planner schemas ────────────────────────────────────────────────

class PhaseDecision(BaseModel):
    """Output of the strategic planner."""

    current_phase:   str = Field(..., description=f"One of: {', '.join(PHASES)}")
    phase_objective: str = Field(..., description="Specific, scoped objective for the tactical planner this phase")
    final_answer:    str = Field(default="", description="Set ONLY when entire pentest is complete")


class ReviewerOutput(BaseModel):
    """Output of the plan reviewer node."""
    status: str = Field(..., description="'approved' | 'edited'")
    task_list: List[Task] = Field(default_factory=list, description="The final vetted list of tasks")
    edit_summary: str = Field(..., description="Summary of edits performed and rationale")