# strategic_plan0.py
"""
Strategic planner for pentest orchestration.
Manages phase progression (recon -> enumeration -> vuln_analysis ->
exploitation -> reporting), maintains the target knowledge graph, and
decides when the overall objective is complete.

Called far less frequently than the tactical planner (once per phase
transition, not once per task), so can use a smaller/cheaper model.
"""

import json
from dotenv import load_dotenv
load_dotenv()
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

from prototype.sub_agents.helper import extract_json_block
from app.utilities import dc_logger
from app.utilities.llm_helper import LLMHelper
from prototype.sub_agents.schemas import (
    PhaseDecision,
    MasterState,
    PHASE_AGENT_MAP,
    void_knowledge,
    merge_knowledge,
    PHASES,
)

logger=dc_logger.LoggerAdap(dc_logger.get_logger(__name__))

#llm setup - strategic planner runs infrequently, so smaller model is fine
strategic_llm=LLMHelper.get_llm_for_service("strategic_planner")
strategic_parser=PydanticOutputParser(pydantic_object=PhaseDecision)

#prompts

def get_strategic_system_prompt()->str:
    phase_lines=[]
    for p in PHASES:
        agents=PHASE_AGENT_MAP.get(p, [])
        agent_str = ", ".join(agents) if agents else "none - synthesis only"
        phase_lines.append(f" - {p.upper()} (agents: {agent_str})")
    phases_block="\n".join(phase_lines)

    return f"""
    You are the strategic phase manager for an automated web pentesting framework.
    PHASES (typically in order, but can loop back if new attack surface is discovered):
    {phases_block}

    PHASE DESCRIPTIONS:
    - RECON: identify open ports, services, web technology stack
    - ENUMERATION: discover endpoints, files, directories, parameters on confirmed web services
    - VULN_ANALYSIS: probe discovered input points for vulnerabilities for impact
    - EXPLOITATION: confirm/exploit indentified vulerabilities for impact
    - REPORTING: synthesize all findings into a final report (no agent execution)

    YOUR JOB EACH CYCLE:
    1. Review the knowledge graph and the summary of the phase that just completed
    2. Decide the next phase:
    - Usually advance to the next phase in order
    - LOOP BACK to an earlier phase (e.g. RECON or ENUMERATION) if the
        knowledge graph reveals new attack surface (new web service, new vhost,
        new port) that hasn't been explored yet
    - STAY in the current phase only if you have a good reason (the tactical
        planner already signals phase completion via phase_summary, so normally
        you should move on)
    3. Set "phase_objective" - a specific, scoped goal for the tactical planner.
    Be concrete: reference actual hosts/ports/endpoints/params from the
    knowledge graph, not generic instructions.
    4. Set "current_phase" to whichever phase you've decided on next
    5. Only when REPORTING has produced a synthesis (i.e. you are CURRENTLY
    deciding the result of a completed REPORTING phase), set "final_answer"
    to the complete pentest report and leave phase_objective empty
    6. Explain your reasoning in "thinking"

    IMPORTANT:
    - Do NOT generate individual agent tasks - that is the tactical planner's job
    - Base decisions on the knowledge graph and phase summaries, not raw logs
    - If findings list is empty after vuln_analysis/exploitation, that's a valid
    outcome - proceed to REPORTING and report "no vulnerabilities found"

    OUTPUT FORMAT:
    """ + strategic_parser.get_format_instructions()

def get_strategic_user_prompt(state: MasterState) -> str:
    knowledge = state.get("knowledge", void_knowledge())
    phase_history = state.get("phase_history", [])
    current_phase = state.get("current_phase", "")

    if not phase_history:
        phase_history_str = "No phases completed yet - this is the start of the pentest"
    else:
        items = []
        for i, rec in enumerate(phase_history, 1):
            items.append(
                f"{i}. [{rec['phase']}] ({rec['iterations']} iterations)\n"
                f"   Summary: {rec['summary']}"
            )
        phase_history_str = "\n\n".join(items)

    last_summary = phase_history[-1]["summary"] if phase_history else "N/A"
    last_phase = phase_history[-1]["phase"] if phase_history else "N/A"

    return f"""ORIGINAL OBJECTIVE:
{state['query']}

CURRENT/PREVIOUS PHASE: {current_phase or "not started"}

MOST RECENTLY COMPLETED PHASE: {last_phase}
ITS SUMMARY: {last_summary}

FULL KNOWLEDGE GRAPH (accumulated across all phases):
{json.dumps(knowledge, indent=2)}

PHASE HISTORY:
{phase_history_str}

Based on the knowledge graph and phase history above, decide the next phase
and its objective. If the most recently completed phase was REPORTING,
produce the final_answer instead.
"""


#planning logic
def strategic_planner(state: MasterState) -> MasterState:
    """
    Decide the next phase and its objective, merging any pending
    extracted_knowledge from the tactical planner into the knowledge graph.
    """
    # Merge knowledge extracted by the tactical planner during the
    # just-completed phase (merge_knowledge_node already does this in the
    # graph, but we guard here too in case strategic is called directly)
    knowledge = state.get("knowledge", void_knowledge())

    messages = [
        SystemMessage(content=get_strategic_system_prompt()),
        HumanMessage(content=get_strategic_user_prompt({**state, "knowledge": knowledge}))
    ]

    try:
        response = strategic_llm.invoke(messages)
        decision = strategic_parser.parse(extract_json_block(response.content))

        if decision.current_phase not in PHASES:
            logger.warning(f"[strategic] Invalid phase '{decision.current_phase}', defaulting to 'reporting'")
            decision.current_phase = "reporting"

        return {
            **state,
            "current_phase": decision.current_phase,
            "phase_objective": decision.phase_objective,
            "final_answer": decision.final_answer,
            "phase_iteration_count": 0,
            "thinking": decision.thinking,
        }

    except Exception as e:
        logger.error(f"[ERROR] Strategic planner failed: {e}")
        logger.info(f"Raw response: {response.content if 'response' in locals() else 'N/A'}")

        # Fail safe: force toward reporting to avoid infinite loops
        next_phase = "reporting" if state.get("current_phase") != "reporting" else "reporting"
        final = ""
        if state.get("current_phase") == "reporting":
            final = f"Error: Strategic planner failed during reporting - {str(e)}"

        return {
            **state,
            "current_phase": next_phase,
            "phase_objective": "Synthesize all findings from the knowledge graph into a final report" if next_phase == "reporting" else "",
            "final_answer": final,
            "phase_iteration_count": 0,
            "thinking": f"Error: {str(e)}",
        }