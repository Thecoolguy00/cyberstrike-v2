# tactical_planner_module.py
"""
Tactical planner — generates batched, dependency-tagged tasks for the
current phase. Reads the VulnNudge from the advisor and folds it into
its planning prompt every cycle.
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
)

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))
load_dotenv()

tactical_llm    = LLMHelper.get_llm_for_service("tactical_planner")
tactical_parser = PydanticOutputParser(pydantic_object=TacticalPlan)


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
━━━ ADVISOR NUDGE ({nudge.priority.upper()}) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


# ─── System prompt ────────────────────────────────────────────────────────────

def get_tactical_system_prompt(
    phase: str,
    phase_objective: str,
    nudge: Optional[VulnNudge] = None,
) -> str:
    allowed_agents = PHASE_AGENT_MAP.get(phase, [])
    agent_descriptions = {
        "nmap_a":  "nmap_a  — Port/service discovery (start light, escalate if needed)",
        "curl_a":  "curl_a  — HTTP inspection (headers, pages, endpoints, custom requests)",
        "ferox_a": "ferox_a — Directory/file enumeration (confirmed web services only)",
        "python_a":"python_a — Write and execute custom Python scripts",
        "xss_a":   "xss_a   — XSS payload injection and detection",
    }
    agent_lines = "\n".join(
        f"- {agent_descriptions[a]}" for a in allowed_agents if a in agent_descriptions
    ) or "- No agents available. Return empty plan + phase_summary immediately."

    nudge_section = _nudge_block(nudge, allowed_agents)

    return f"""You are a tactical task planner for ONE phase of a web pentest.

CURRENT PHASE: {phase}
PHASE OBJECTIVE (set by strategic planner — overall scope for this phase):
{phase_objective}

AGENTS AVAILABLE THIS PHASE:
{agent_lines}
{nudge_section}
BATCH PLANNING MODEL:
- Generate ALL tasks you can identify for this cycle in ONE response
- Tag truly independent tasks with empty depends_on — they run in PARALLEL
- Use depends_on: ["task_id"] only for real ordering constraints
- Every task MUST have a unique task_id (short slug, no spaces)
- More tasks per cycle = fewer total cycles = faster execution

Example batch (recon):
  task_id="nmap_quick",   depends_on=[],             agent=nmap_a
  task_id="curl_root",    depends_on=[],             agent=curl_a
  task_id="curl_headers", depends_on=["curl_root"],  agent=curl_a  ← waits for root

PLANNING RULES:
0. Start with less intrusive techniques, escalate only if needed
1. Address HIGH priority advisor nudges first (include at least one nudge task)
2. Only plan tasks executable NOW with current knowledge
3. ONLY use agents from the allowed list — others are dropped silently
4. Note out-of-scope observations in extracted_knowledge.notes (don't pursue them)
5. When phase objective is fully satisfied OR no useful tasks remain:
   - Return EMPTY "plan"
   - Set "phase_summary" summarising what was found
   - Populate "extracted_knowledge" fully
6. ALWAYS populate extracted_knowledge every cycle — even mid-phase

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

    knowledge = state.get("knowledge", void_knowledge())

    return f"""ORIGINAL OBJECTIVE:
{state['query']}

PHASE OBJECTIVE:
{state['phase_objective']}

CURRENT KNOWLEDGE GRAPH:
{json.dumps(knowledge, indent=2)}

EXECUTION HISTORY FOR THIS PHASE:
{history_str}

MCP BACKGROUND TASKS STATUS:
{status_str}

What is the FULL batch of tasks for this cycle?
- Include ALL independent work (they run in parallel — no cost to batching)
- If advisor nudge is HIGH priority, include at least one nudge task
- If phase is complete: empty plan + phase_summary + extracted_knowledge
- Do NOT repeat tasks that already succeeded above
"""


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

    Key behaviours added vs previous version:
    - Reads VulnNudge from state and injects it into the system prompt
    - Prompts for batch + parallel task generation (task_id, depends_on)
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

        return {
            **state,
            "plan":                  validated_plan,
            "phase_iteration_count": state.get("phase_iteration_count", 0) + 1,
            "_phase_summary":        parsed.phase_summary,
            "_extracted_knowledge":  parsed.extracted_knowledge,
            "thinking":              parsed.thinking,
            # append to checked_vulns via the reducer in MasterState
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