from langchain_core.tools import retriever
from typing import Annotated, List, Dict, TypedDict, Optional
import operator
from pydantic import BaseModel, Field
from langgraph.graph import MessagesState

class BaseState(MessagesState):
    tool_used:Annotated[List[str],operator.add]
    task:str

#Shared schema, types and knowledge graph definitions for dual-planner (strategic + tactical) orchestrator

PHASES=["recon", "enumeration", "vuln_analysis", "exploitation", "reporting"]
#in the prompt for strategic mention clear that when each phase should begin/end

PHASE_AGENT_MAP: Dict[str, List[str]] = {
    "recon": ["nmap_a", "curl_a"],
    "enumeration": ["ferox_a", "curl_a"],
    "vuln_analysis": ["xss_a", "curl_a", "python_a"],
    "exploitation": ["python_a", "xss_a", "curl_a"],
    "reporting": [],  # no agent execution - strategic synthesizes final answer
}

MAX_PHASE_ITERATIONS = 8  # safety cap per phase before forced advance

#Knowledge graph
class OpenPort(TypedDict, total=False):
    port:int
    service:str
    version:str
    state:str

class WebService(TypedDict, total=False):
    url:str
    port:int
    tech_stack: List[str]
    headers: Dict[str, str]
    title:str

class InputPoint(TypedDict, total=False):
    url:str
    param:str
    method:str
    context:str #e.g. "reflected in html body", "json response"

class Finding(TypedDict, total=False):
    type:str #e.g. "xss", "open_redirect", "info_disclosure"
    location:str
    serverity:str # info|low|medium|high|critical
    confirmed:bool
    description:str

class TargetKnowledge(TypedDict, total=False):
    # open_ports: Annotated[List[OpenPort], operator.add()], can't we just do this?
    open_ports: List[OpenPort]
    web_services: List[WebService]
    endpoints: List[str]
    input_points: List[InputPoint]
    findings: List[Finding]
    notes: List[str]

def void_knowledge()->TargetKnowledge:
    return TargetKnowledge(
        open_ports=[],
        web_services=[],
        endpoints=[],
        input_points=[],
        findings=[],
        notes=[],
    )

def merge_knowledge(base: TargetKnowledge, update: TargetKnowledge) -> TargetKnowledge:
    """
    Merge an incoming knowledge update into the base knowledge graph.
    Lists are concatenated with simple de-duplication on key fields.
    """
    if not update:
        return base

    merged: TargetKnowledge = {
        "open_ports": list(base.get("open_ports", [])),
        "web_services": list(base.get("web_services", [])),
        "endpoints": list(base.get("endpoints", [])),
        "input_points": list(base.get("input_points", [])),
        "findings": list(base.get("findings", [])),
        "notes": list(base.get("notes", [])),
    }

    # open_ports: dedupe by port number
    existing_ports = {p.get("port") for p in merged["open_ports"]}
    for p in update.get("open_ports", []) or []:
        if p.get("port") not in existing_ports:
            merged["open_ports"].append(p)
            existing_ports.add(p.get("port"))

    # web_services: dedupe by url
    existing_urls = {s.get("url") for s in merged["web_services"]}
    for s in update.get("web_services", []) or []:
        if s.get("url") not in existing_urls:
            merged["web_services"].append(s)
            existing_urls.add(s.get("url"))
        else:
            # merge tech_stack/headers into existing entry
            for existing in merged["web_services"]:
                if existing.get("url") == s.get("url"):
                    existing_stack = set(existing.get("tech_stack", []) or [])
                    existing_stack.update(s.get("tech_stack", []) or [])
                    existing["tech_stack"] = list(existing_stack)
                    existing.setdefault("headers", {}).update(s.get("headers", {}) or {})

    # endpoints: dedupe as a set, keep order
    existing_endpoints = set(merged["endpoints"])
    for e in update.get("endpoints", []) or []:
        if e not in existing_endpoints:
            merged["endpoints"].append(e)
            existing_endpoints.add(e)

    # input_points: dedupe by (url, param, method)
    existing_inputs = {
        (ip.get("url"), ip.get("param"), ip.get("method")) for ip in merged["input_points"]
    }
    for ip in update.get("input_points", []) or []:
        key = (ip.get("url"), ip.get("param"), ip.get("method"))
        if key not in existing_inputs:
            merged["input_points"].append(ip)
            existing_inputs.add(key)

    # findings: dedupe by (type, location)
    existing_findings = {
        (f.get("type"), f.get("location")) for f in merged["findings"]
    }
    for f in update.get("findings", []) or []:
        key = (f.get("type"), f.get("location"))
        if key not in existing_findings:
            merged["findings"].append(f)
            existing_findings.add(key)
        else:
            # update confirmation status if newly confirmed
            for existing in merged["findings"]:
                if (existing.get("type"), existing.get("location")) == key:
                    if f.get("confirmed"):
                        existing["confirmed"] = True
                    if f.get("description"):
                        existing["description"] = f.get("description")

    # notes: append all, dedupe exact matches
    existing_notes = set(merged["notes"])
    for n in update.get("notes", []) or []:
        if n not in existing_notes:
            merged["notes"].append(n)
            existing_notes.add(n)

    return merged


def _merge_str_lists(left: Optional[List[str]], right: Optional[List[str]]) -> List[str]:
    """Merge two lists of strings, deduplicating them while preserving order."""
    if left is None:
        left = []
    if right is None:
        right = []
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged


# vulnerability scheme
class VulnFocus(BaseModel):
    """Directive from the vuln advisor to the tactical planner."""
    vuln_id: str = Field("", description="Unique slug e.g 'reflected_xss', 'git_exposure'")
    label: str = Field("", description="Human-friendly label for the vulnerability e.g 'Reflected XSS'")
    rationale: str = Field("", description="Why this vuln now - what in the knowledge graph triggered it")
    specific_targets: List[str] = Field(default_factory=list, description="Concrete URLs/params/endpoints to probe from the knowledge graph")
    suggested_agents: List[str] = Field(default_factory=list, description="Agents that can probe this - must be subset of phase agents")
    skip_reason: str = Field("", description="Set ONLY when nothing viable remains - leave all other fields empty")


# master state

class PhaseHistoryRecord(TypedDict):
    phase: str
    summary: str
    iterations: int

class MasterState(TypedDict, total=False):
    query:str

    #phase tracking
    current_phase:str
    phase_objective:str
    phase_iteration_count:int

    #knowledge
    knowledge: TargetKnowledge

    #execution
    plan: List[dict]
    execution_history: List[Dict[str, str]]
    phase_history: List[PhaseHistoryRecord]

    #internal handoff fields (tactical -> strategic)
    _phase_summary:str
    _extracted_knowledge: TargetKnowledge

    # vuln advisor handoff
    vuln_focus:    Optional[VulnFocus]              # set by advisor, read by tactical, cleared when focus exhausted
    checked_vulns: Annotated[List[str], _merge_str_lists]  # vuln_ids attempted, persists across whole pentest

    #final
    final_answer: str
    thinking: str


#tactical planner schemas

class Task(BaseModel):
    """Single task for an agent"""
    agent:str=Field(..., description="agent name, must be one of the agents allowed for the current phase")
    task_description:str=Field(..., description="clear, specific task instruction")

class TacticalPlan(BaseModel):
    """output of the tactical planner for a single phase cycle"""
    plan: List[Task]=Field(
        default_factory=list,
        description="Next tasks to execute (empty if this phase's objective is satisfied)"
    )
    phase_summary: str = Field(
        default="",
        description="Summary of this phase's findings - set ONLY when plan is empty (phase complete)"
    )
    extracted_knowledge: TargetKnowledge = Field(
        default_factory=void_knowledge,
        description="Structured findings extracted from execution results to merge into the knowledge graph"
    )
    thinking:str=Field(..., description="reasoning for the current plan/decision")


#strategic planner schemas
class PhaseDecision(BaseModel):
    """output of the strategic planner"""
    current_phase:str=Field(..., description=f"One of: {', '.join(PHASES)}")
    phase_objective:str=Field(..., description="specific, scoped objective for the tactical planner to pursue this phase")
    final_answer:str=Field(default="",description="set ONLY when the entire pentest is complete (after reporting phase synthesis)")
    thinking:str=Field(...,description="Reasoning for this phase decision")