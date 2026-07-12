# tactical_planner_module.py
"""
Tactical planner — generates batched, dependency-tagged tasks for the
current phase. Reads the VulnNudge from the advisor and folds it into
its planning prompt every cycle.

Key addition vs previous version:
  Each phase now receives a PHASE PLAYBOOK — a concrete SOP injected
  into the system prompt that tells the LLM exactly what the execution
  order is, what prerequisites are required before escalating, and what
  is explicitly forbidden. This eliminates the "curl before nmap" class
  of bugs where the planner guesses at sequencing instead of following
  a defined procedure.

  A matching ADVISOR GUARDRAIL block is injected into vuln_advisor.py
  (see ADVISOR_PHASE_GUARDRAILS at the bottom of this file — imported
  by vuln_advisor to keep guardrails co-located with the playbooks they
  mirror).
"""

import asyncio
import json
from typing import Dict, List, Optional
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

from prototype.sub_agents.helper import extract_json_block
from app.utilities import dc_logger
from prototype.sub_agents.true_mcp_exec import run_mcp_tool
from app.utilities.llm_helper import LLMHelper
from prototype.sub_agents.schemas import (
    TacticalPlan,
    MasterState,
    PHASE_AGENT_MAP,
    void_knowledge,
    VulnNudge,
    merge_knowledge,
)

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))
load_dotenv()

tactical_llm    = LLMHelper.get_llm_for_service("tactical_planner")
tactical_parser = PydanticOutputParser(pydantic_object=TacticalPlan)


# ─── Global rules + phase playbooks ─────────────────────────────────────────
# GLOBAL_RULES is injected into every phase prompt — keeps individual
# playbooks short and ensures consistent discipline across all phases.
# Each playbook covers ONE phase with a compact, state-based SOP.

GLOBAL_RULES = """
GLOBAL RULES
- The knowledge graph is the source of truth.
- Only interact with assets confirmed in the knowledge graph.
- Never repeat work already in the execution history.
- Only plan tasks that are executable right now.
- Batch independent tasks (empty depends_on = parallel).
- Return an empty plan when the phase objective is complete.
"""

RECON_PLAYBOOK = """
RECON

Objective
Discover reachable services.

State

IF knowledge.open_ports is empty
→ Discover ports.

IF confirmed HTTP services exist but are not fingerprinted
→ Fingerprint them.

IF no HTTP services exist
→ Finish phase.

Forbidden
- Interact only with confirmed ports and services.
- No enumeration.
- No vulnerability testing.
"""

ENUMERATION_PLAYBOOK = """
ENUMERATION

Objective
Map web attack surface.

State

IF knowledge.web_services is empty
→ Finish phase.

IF endpoints are incomplete
→ Enumerate endpoints.

IF input_points are incomplete
→ Inspect endpoints for parameters and forms.

IF attack surface is mapped
→ Finish phase.

Forbidden
- No vulnerability testing.
- No new reconnaissance.
"""

VULN_ANALYSIS_PLAYBOOK = """
VULNERABILITY ANALYSIS

Objective
Identify vulnerabilities.

Priority

1. User-requested vulnerability type (check original query).
2. Input-based testing (XSS, SQLi, HTMLi, open redirect, IDOR).
3. Endpoint-based testing (backup files, source disclosure, directory listing).
4. Configuration checks (CORS, clickjacking, cookie flags, secret leaks).

Forbidden
- No exploitation.
- No new enumeration.
- No reconnaissance.
"""

EXPLOITATION_PLAYBOOK = """
EXPLOITATION

Objective
Confirm findings.

State

IF no findings
→ Finish phase.

IF findings remain unconfirmed
→ Confirm them with proof-of-concept.

IF multiple findings relate (same endpoint, session, user)
→ Attempt chaining.

Forbidden
- No destructive actions.
- No new discovery.
"""

REPORTING_PLAYBOOK = """
REPORTING

No agent execution.

Return:
- empty plan
- phase summary
- extracted knowledge
"""

TACTICAL_PHASE_PLAYBOOKS: Dict[str, str] = {
    "recon":         RECON_PLAYBOOK,
    "enumeration":   ENUMERATION_PLAYBOOK,
    "vuln_analysis": VULN_ANALYSIS_PLAYBOOK,
    "exploitation":  EXPLOITATION_PLAYBOOK,
    "reporting":     REPORTING_PLAYBOOK,
}


# ─── Nudge block injected into system prompt ──────────────────────────────────

def _nudge_block(nudge: Optional[VulnNudge], allowed_agents: List[str]) -> str:
    """
    Render the advisor's VulnNudge as a prompt block.
    Only injected when priority is high or medium.
    """
    if not nudge or nudge.priority == "skip" or not nudge.vuln_id:
        return ""

    valid_agents = [a for a in nudge.suggested_agents if a in allowed_agents]
    agents_str   = ", ".join(valid_agents) if valid_agents else "any available agent"
    targets_str  = "\n".join(f"  - {t}" for t in nudge.specific_targets) or "  - derive from knowledge graph"

    urgency = (
        "⚠ HIGH PRIORITY — address this BEFORE other tasks this cycle."
        if nudge.priority == "high"
        else "ℹ MEDIUM PRIORITY — fold into current work if not too costly."
    )

    return f"""
ADVISOR NUDGE ({nudge.priority.upper()})
  {urgency}
  Vulnerability:    {nudge.label} [{nudge.vuln_id}]
  Why now:          {nudge.rationale}
  Suggested agents: {agents_str}
  Targets:
{targets_str}

  HOW TO HANDLE:
  - If priority=high: include at least one task probing this vuln in the plan.
    Assign it an empty depends_on so it runs in parallel with other ready tasks.
  - If priority=medium: include it if it fits naturally; skip if plan is already full.
  - When you return an EMPTY plan (focus exhausted), set phase_summary and the
    graph will automatically mark "{nudge.vuln_id}" as checked.
"""


# ─── System prompt ────────────────────────────────────────────────────────────

def get_tactical_system_prompt(
    phase: str,
    phase_objective: str,
    nudge: Optional[VulnNudge] = None,
) -> str:
    allowed_agents = PHASE_AGENT_MAP.get(phase, [])
    agent_descriptions = {
        "nmap_a":   "nmap_a   — Network port and service discovery",
        "http_a":   "http_a   — Full HTTP agent: any method (GET/POST/PUT/DELETE/OPTIONS/"
                    "PROPFIND/PATCH), headers, cookies, JSON/form/raw body, presets "
                    "(browser/api/webdav). Use this for all HTTP interaction.",
        "ferox_a":  "ferox_a  — Directory and file enumeration on confirmed web services",
        "python_a": "python_a — Write and execute custom Python scripts for any task",
        "xss_a":    "xss_a    — XSS payload injection and detection",
        "intel_a":  "intel_a  — Exploit intelligence: searches Tavily, ExploitDB, GitHub, "
                    "and NVD for known CVEs and public PoCs for a given technology/version. "
                    "Use when a versioned service is identified. "
                    "Task format: 'Research <technology> <version> for known vulnerabilities'",
    }
    agent_lines = "\n".join(
        f"- {agent_descriptions[a]}" for a in allowed_agents if a in agent_descriptions
    ) or "- No agents available. Return empty plan + phase_summary immediately."

    playbook      = TACTICAL_PHASE_PLAYBOOKS.get(phase, "")
    nudge_section = _nudge_block(nudge, allowed_agents)

    return f"""You are a tactical task planner for ONE phase of a web pentest.

CURRENT PHASE: {phase}
PHASE OBJECTIVE (set by strategic planner):
{phase_objective}

AGENTS AVAILABLE THIS PHASE:
{agent_lines}

{GLOBAL_RULES}
{playbook}
{nudge_section}
Note out-of-scope observations in extracted_knowledge.notes (don't pursue them).
ALWAYS populate extracted_knowledge every cycle — even mid-phase.

OUTPUT FORMAT:
""" + tactical_parser.get_format_instructions()


# ─── User prompt ──────────────────────────────────────────────────────────────

def get_tactical_user_prompt(
    state: MasterState,
    phase_execution_history: List[Dict[str, str]],
) -> str:
    try:
        status_result = asyncio.run(run_mcp_tool("get_all_bg_task_status", {}))
        if not isinstance(status_result, dict):
            status_str = str(status_result)
        elif status_result.get("total", 0) == 0:
            status_str = "no background tasks dispatched yet"
        else:
            status_str = json.dumps(status_result, indent=2)
    except Exception as e:
        status_str = f"Error fetching — {e}"

    if not phase_execution_history:
        history_str = "None yet — first planning cycle for this phase"
    else:
        items = []
        for i, ex in enumerate(phase_execution_history, 1):
            items.append(
                f"{i}. [{ex['agent']}] {ex['task']}\n"
                f"   ➜ {ex.get('result', 'No result')}"
            )
        history_str = "\n\n".join(items)

    # Merge live cycle-level discoveries into the committed knowledge base
    # so tactical sees its own previous output within a phase, not just
    # what was committed at the last phase boundary.
    knowledge = merge_knowledge(
        state.get("knowledge", void_knowledge()),
        state.get("_extracted_knowledge", void_knowledge()),
    )

    # Surface a quick prerequisite summary so the LLM doesn't have to
    # re-derive it from the full knowledge graph on every cycle.
    phase = state.get("current_phase", "")
    prereq_summary = _build_prereq_summary(phase, knowledge)

    return f"""ORIGINAL OBJECTIVE:
{state['query']}

PHASE OBJECTIVE:
{state['phase_objective']}

PREREQUISITE STATUS (derived from knowledge graph):
{prereq_summary}

CURRENT KNOWLEDGE GRAPH:
{json.dumps(knowledge, indent=2)}

EXECUTION HISTORY FOR THIS PHASE:
{history_str}

MCP BACKGROUND TASKS STATUS:
{status_str}

Refer to the PHASE PLAYBOOK in your instructions for the correct execution
order and prerequisites. Then output the FULL batch of tasks for this cycle:
- Tasks that are truly independent go in the same batch with empty depends_on
- Tasks that must wait for others use depends_on referencing the earlier task_id
- If a prerequisite step is not yet complete, plan only up to that step
- If phase is complete: empty plan + phase_summary + extracted_knowledge
- Do NOT repeat tasks that already succeeded in the execution history above
"""


def _build_prereq_summary(phase: str, knowledge: dict) -> str:
    """
    Quick prerequisite check surfaced verbatim into the user prompt.
    Helps the LLM validate gating conditions without reading the full KG.
    """
    open_ports   = knowledge.get("open_ports",   []) or []
    web_services = knowledge.get("web_services", []) or []
    endpoints    = knowledge.get("endpoints",    []) or []
    input_points = knowledge.get("input_points", []) or []
    findings     = knowledge.get("findings",     []) or []

    http_ports = [
        p for p in open_ports
        if any(kw in str(p.get("service", "")).lower()
               for kw in ("http", "https", "web", "ssl"))
    ]

    lines = [
        f"  open_ports:      {len(open_ports)} known  "
        f"({'includes HTTP/HTTPS' if http_ports else 'no HTTP ports confirmed yet'})",
        f"  web_services:    {len(web_services)} confirmed URL(s)",
        f"  endpoints:       {len(endpoints)} discovered",
        f"  input_points:    {len(input_points)} known",
        f"  findings:        {len(findings)} recorded",
    ]

    # Phase-specific gate warnings
    if phase == "recon" and not open_ports:
        lines.append("  ⚠ GATE: No ports known yet — start with nmap, not curl.")
    if phase == "recon" and open_ports and not http_ports:
        lines.append("  ⚠ GATE: No HTTP ports confirmed — do NOT run curl until nmap finds one.")
    if phase == "enumeration" and not web_services:
        lines.append("  ⚠ GATE: No web services — skip phase (return empty plan).")
    if phase == "vuln_analysis" and not input_points and not endpoints:
        lines.append("  ⚠ GATE: No input_points or endpoints — limited probing possible.")
    if phase == "exploitation" and not findings:
        lines.append("  ⚠ GATE: No findings to confirm — skip phase (return empty plan).")

    return "\n".join(lines)


# ─── History slicer ───────────────────────────────────────────────────────────

def get_phase_execution_history(state: MasterState) -> List[Dict[str, str]]:
    full_history  = state.get("execution_history", [])
    phase_history = state.get("phase_history",     [])
    if not phase_history:
        return full_history
    consumed = sum(rec.get("executions_consumed", 0) for rec in phase_history)
    return full_history[consumed:]


# ─── Node ─────────────────────────────────────────────────────────────────────

def tactical_planner(state: MasterState) -> dict:
    """
    Generate a batch of tasks for this cycle.

    Key behaviours:
    - Injects phase-specific playbook (SOP with execution order + forbidden actions)
    - Injects prerequisite summary so the LLM sees gate status explicitly
    - Reads VulnNudge from state and folds it into the system prompt
    - When returning an empty plan (focus/phase done), adds the current
      nudge's vuln_id to checked_vulns so the advisor never re-suggests it
    """
    phase              = state["current_phase"]
    phase_objective    = state.get("phase_objective", "")
    phase_exec_history = get_phase_execution_history(state)
    nudge              = state.get("vuln_nudge")

    messages = [
        SystemMessage(content=get_tactical_system_prompt(phase, phase_objective, nudge)),
        HumanMessage(content=get_tactical_user_prompt(state, phase_exec_history)),
    ]

    try:
        response = tactical_llm.invoke(messages)
        parsed: TacticalPlan = tactical_parser.parse(extract_json_block(response.content))

        allowed_agents = PHASE_AGENT_MAP.get(phase, [])
        validated_plan = [t.model_dump() for t in parsed.plan if t.agent in allowed_agents]
        dropped = [t.agent for t in parsed.plan if t.agent not in allowed_agents]
        if dropped:
            logger.warning(f"[tactical] Dropped out-of-scope agents for '{phase}': {dropped}")

        # When tactical signals phase/focus done (empty plan), mark the current
        # nudge's vuln_id as checked so advisor never re-suggests it.
        newly_checked: List[str] = []
        if not validated_plan and nudge and nudge.vuln_id and nudge.priority != "skip":
            newly_checked = [nudge.vuln_id]
            logger.info(f"[tactical] Marking '{nudge.vuln_id}' as checked")

        # Accumulate this cycle's extraction into the running _extracted_knowledge
        # so knowledge builds up across cycles within a phase rather than being
        # reset each time tactical runs.
        accumulated = merge_knowledge(
            state.get("_extracted_knowledge", void_knowledge()),
            parsed.extracted_knowledge,
        )

        return {
            **state,
            "plan":                  validated_plan,
            "phase_iteration_count": state.get("phase_iteration_count", 0) + 1,
            "_phase_summary":        parsed.phase_summary,
            "_extracted_knowledge":  accumulated,
            "thinking":              parsed.thinking,
            "checked_vulns":         newly_checked,
        }

    except Exception as e:
        logger.error(f"[ERROR] Tactical planner failed: {e}")
        logger.info(f"Raw response: {response.content if 'response' in locals() else 'N/A'}")
        return {
            **state,
            "plan":                  [],
            "phase_iteration_count": state.get("phase_iteration_count", 0) + 1,
            "_phase_summary":        f"Phase ended due to planner error: {e}",
            "_extracted_knowledge":  void_knowledge(),
            "thinking":              f"Error: {e}",
            "checked_vulns":         [],
        }