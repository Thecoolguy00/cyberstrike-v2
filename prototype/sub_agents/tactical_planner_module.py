# tactical_plan0.py
"""
Tactical planner for pentest orchestration.
Operates within a single phase, generating concrete agent tasks
using a plan-execute-feedback loop scoped to the strategic planner's
phase_objective.
"""

import asyncio
import json
from typing import Dict, List
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
    VulnFocus,
)

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))
load_dotenv()

# LLM setup - tactical planner runs frequently, can use a faster/cheaper model
tactical_llm = LLMHelper.get_llm_for_service("tactical_planner")

tactical_parser = PydanticOutputParser(pydantic_object=TacticalPlan)


# ============= Prompts =============

def get_tactical_system_prompt(phase: str, phase_objective: str, vuln_focus: VulnFocus = None) -> str:
    allowed_agents = PHASE_AGENT_MAP.get(phase, [])
    agent_descriptions = {
        "nmap_a":  "nmap_a  - Port/service discovery (start light, escalate if needed)",
        "curl_a":  "curl_a  - HTTP inspection (headers, pages, endpoints)",
        "ferox_a": "ferox_a - Directory/file enumeration (only on confirmed web services)",
        "python_a":"python_a- Write and execute custom Python scripts",
        "xss_a":   "xss_a   - XSS testing (only on confirmed input points)",
    }
    agent_lines = "\n".join(
        f"- {agent_descriptions[a]}" for a in allowed_agents if a in agent_descriptions
    ) or "- No agents available. Return empty plan + phase_summary immediately."

    # vuln focus block — only injected in vuln_analysis when advisor produced a focus
    focus_block = ""
    if vuln_focus and vuln_focus.vuln_id:
        suggested = ", ".join(vuln_focus.suggested_agents) if vuln_focus.suggested_agents else "any available"
        targets   = "\n".join(f"  - {t}" for t in vuln_focus.specific_targets) or "  - (derive from knowledge graph)"
        focus_block = f"""
VULNERABILITY FOCUS (set by advisor — this is your primary directive):
  Type:              {vuln_focus.label} [{vuln_focus.vuln_id}]
  Why now:           {vuln_focus.rationale}
  Suggested agents:  {suggested}
  Specific targets:
{targets}

FOCUS RULES:
- Probe ONLY this vulnerability type on the listed targets
- Use the suggested agents if they are in the allowed list above
- When this focus is exhausted (all targets tested or confirmed/ruled out):
  return EMPTY plan + phase_summary describing what was found for THIS focus
  The advisor will then pick the next vulnerability to investigate
- Do NOT pivot to other vulns mid-focus, note them in extracted_knowledge.notes
"""

    return f"""You are a tactical task planner for ONE phase of a web pentest.

CURRENT PHASE: {phase}
PHASE OBJECTIVE (set by strategic planner — overall scope):
{phase_objective}

AGENTS AVAILABLE THIS PHASE:
{agent_lines}
{focus_block}
EXECUTION MODEL:
- Generate ONE step (or small batch of independent steps) at a time
- After execution, results are added to history and you're called again
- Base NEXT steps on ACTUAL results, not assumptions

PLANNING RULES:
0. Start with less intrusive techniques, escalate only if needed
1. Only plan tasks executable NOW with current knowledge
2. ONLY use agents listed above — tasks for others are dropped
3. Stay strictly within the current focus (if set) or phase objective
   (note out-of-scope observations in extracted_knowledge.notes instead)
4. When the current focus is exhausted OR phase objective satisfied:
   - Return EMPTY "plan"
   - Set "phase_summary" describing results for this focus/phase
   - Populate "extracted_knowledge" fully
5. ALWAYS populate extracted_knowledge with any structured findings —
   even mid-phase, every cycle
6. Explain reasoning in "thinking" every cycle

OUTPUT FORMAT:
""" + tactical_parser.get_format_instructions()


def get_tactical_user_prompt(state: MasterState, phase_execution_history: List[Dict[str, str]]) -> str:
    """User prompt with current phase state and recent results."""

    # Background task status (MCP) - only relevant to tactical execution
    try:
        status_result = asyncio.run(run_mcp_tool("get_all_bg_task_status", {}))
        if not isinstance(status_result, dict):
            status_str = str(status_result)
        elif status_result.get("total", 0) == 0:
            status_str = "no background tasks have been dispatched yet"
        else:
            status_str = json.dumps(status_result, indent=2)
    except Exception as e:
        status_str = f"Error fetching - {str(e)}"

    # Format phase-scoped execution history
    if not phase_execution_history:
        history_str = "None yet - this is the first planning cycle for this phase"
    else:
        history_items = []
        for i, ex in enumerate(phase_execution_history, 1):
            result = ex.get("result", "No result")
            history_items.append(
                f"{i}. [{ex['agent']}] {ex['task']}\n"
                f"   ➜ Result: {result}"
            )
        history_str = "\n\n".join(history_items)

    knowledge = state.get("knowledge", void_knowledge())

    return f"""ORIGINAL OBJECTIVE:
{state['query']}

PHASE OBJECTIVE (this cycle's scope):
{state['phase_objective']}

CURRENT KNOWLEDGE GRAPH (accumulated across all phases so far):
{json.dumps(knowledge, indent=2)}

EXECUTION HISTORY FOR THIS PHASE (Task → Result):
{history_str}

MCP BACKGROUND TASKS STATUS:
{status_str}

Based on the phase objective, knowledge graph, and execution history above,
what should happen NEXT within this phase?
- If more info needed for THIS phase: Return next task(s) in "plan"
- If the plan includes a background task then mention the corresponding task's id
- If this phase's objective is satisfied: Return empty "plan" + "phase_summary"
  + "extracted_knowledge" with everything learned this phase

IMPORTANT: Don't repeat tasks that already succeeded in this phase's history.
"""


# ============= Planning Logic =============

def get_phase_execution_history(state: MasterState) -> List[Dict[str, str]]:
    """
    Slice execution_history to only entries since the start of the current
    phase. We track this by looking at how many executions occurred before
    the most recent phase_history entry boundary.
    """
    full_history = state.get("execution_history", [])
    phase_history = state.get("phase_history", [])

    if not phase_history:
        return full_history

    # Count executions consumed by completed phases
    consumed = sum(rec.get("executions_consumed", 0) for rec in phase_history)
    return full_history[consumed:]


def tactical_planner(state: MasterState) -> MasterState:
    """
    Plan next tasks within the current phase's scope.

    Returns updated state with either:
      - a non-empty "plan" to execute, or
      - an empty "plan" + "_phase_summary" + "_extracted_knowledge" signalling
        the phase is complete and control should return to the strategic planner.
    """
    phase = state["current_phase"]
    phase_objective = state.get("phase_objective", "")
    phase_exec_history = get_phase_execution_history(state)
    vuln_focus = state.get("vuln_focus")
    
    messages = [
        SystemMessage(content=get_tactical_system_prompt(phase, phase_objective, vuln_focus)),
        HumanMessage(content=get_tactical_user_prompt(state, phase_exec_history)),
    ]

    try:
        response = tactical_llm.invoke(messages)
        parsed = tactical_parser.parse(extract_json_block(response.content))

        allowed_agents = PHASE_AGENT_MAP.get(phase, [])
        validated_plan = [t.model_dump() for t in parsed.plan if t.agent in allowed_agents]

        if len(validated_plan) != len(parsed.plan):
            dropped = [t.agent for t in parsed.plan if t.agent not in allowed_agents]
            logger.warning(f"[tactical] Dropped out-of-scope tasks for phase '{phase}': {dropped}")

        return {
            **state,
            "plan": validated_plan,
            "phase_iteration_count": state.get("phase_iteration_count", 0) + 1,
            "_phase_summary": parsed.phase_summary,
            "_extracted_knowledge": parsed.extracted_knowledge,
            "thinking": parsed.thinking,
        }

    except Exception as e:
        logger.error(f"[ERROR] Tactical planner failed: {e}")
        logger.info(f"Raw response: {response.content if 'response' in locals() else 'N/A'}")

        # Fail safe: end the phase rather than loop forever on a broken response
        return {
            **state,
            "plan": [],
            "phase_iteration_count": state.get("phase_iteration_count", 0) + 1,
            "_phase_summary": f"Phase ended due to planner error: {str(e)}",
            "_extracted_knowledge": void_knowledge(),
            "thinking": f"Error: {str(e)}",
        }