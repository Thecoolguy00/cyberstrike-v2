# master_graph.py
"""
Master orchestration graph wiring the strategic planner, tactical planner,
and agent execution layer together with phase/knowledge-graph management.
"""

from typing import Literal
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from app.utilities import dc_logger
from prototype.sub_agents.schemas import (
    MasterState,
    PhaseHistoryRecord,
    PHASES,
    MAX_PHASE_ITERATIONS,
    void_knowledge,
    merge_knowledge,
)
from prototype.sub_agents.strategic_planner_module import strategic_planner
from prototype.sub_agents.tactical_planner_module import tactical_planner
from prototype.sub_agents.executor import execute_plan
from prototype.sub_agents.vuln_advisor import vuln_advisor
from prototype.sub_agents.schemas import VulnFocus

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))
load_dotenv()


# ============= Graph Nodes =============

def execute_node(state: MasterState) -> MasterState:
    """Execute the current plan via the agent execution layer."""
    plan = state.get("plan", [])
    executions = execute_plan(plan, verbose=True)

    return {
        **state,
        "execution_history": state.get("execution_history", []) + executions,
        "plan": [],
    }


def merge_knowledge_node(state: MasterState) -> MasterState:
    """
    Called when the tactical planner signals phase completion
    (_phase_summary set). Merges extracted knowledge into the master
    knowledge graph and records a phase_history entry, including how many
    execution_history entries belong to the completed phase (so the next
    phase's tactical planner starts with a clean history slice).
    """
    phase_history = state.get("phase_history", [])
    consumed_so_far = sum(rec.get("executions_consumed", 0) for rec in phase_history)
    total_executions = len(state.get("execution_history", []))
    executions_this_phase = total_executions - consumed_so_far

    record: PhaseHistoryRecord = {
        "phase": state["current_phase"],
        "summary": state.get("_phase_summary", ""),
        "iterations": state.get("phase_iteration_count", 0),
        "executions_consumed": executions_this_phase,  # type: ignore[typeddict-item]
    }

    merged_knowledge = merge_knowledge(
        state.get("knowledge", void_knowledge()),
        state.get("_extracted_knowledge", void_knowledge()),
    )

    if state.get("_phase_summary"):
        logger.info(f"[phase complete] {state['current_phase']}: {state['_phase_summary']}")

    return {
        **state,
        "knowledge": merged_knowledge,
        "phase_history": phase_history + [record],
        "_phase_summary": "",
        "_extracted_knowledge": void_knowledge(),
    }


# ============= Routing =============

def route_after_strategic(state: MasterState) -> Literal["vuln_advisor", "tactical", "end"]:
    if state.get("final_answer"):
        return "end"
    if state["current_phase"] == "vuln_analysis":
        return "vuln_advisor"   # always enter vuln_analysis through the advisor
    return "tactical"


def route_after_tactical(state: MasterState) -> Literal["execute", "vuln_advisor", "merge_knowledge"]:
    if state.get("plan"):
        return "execute"

    iterations = state.get("phase_iteration_count", 0)
    if iterations >= MAX_PHASE_ITERATIONS and not state.get("_phase_summary"):
        logger.warning(
            f"[tactical] Phase '{state['current_phase']}' hit max iterations "
            f"({MAX_PHASE_ITERATIONS}) without signalling completion — forcing advance"
        )
        state["_phase_summary"] = (
            f"Phase '{state['current_phase']}' ended after reaching the iteration "
            f"cap ({MAX_PHASE_ITERATIONS}) without an explicit completion signal."
        )
        return "merge_knowledge"

    # empty plan in vuln_analysis = current focus exhausted, mark it checked
    # and let advisor pick the next one (or skip)
    if state["current_phase"] == "vuln_analysis":
        focus = state.get("vuln_focus")
        if focus and hasattr(focus, "vuln_id") and focus.vuln_id:
            logger.info(f"[tactical] Focus '{focus.vuln_id}' exhausted - marking checked")
            state["checked_vulns"] = state.get("checked_vulns", []) + [focus.vuln_id]
            state["vuln_focus"] = None
        return "vuln_advisor"   # advisor decides: next focus OR skip → merge_knowledge

    return "merge_knowledge"


def route_after_advisor(state: MasterState) -> Literal["tactical", "merge_knowledge"]:
    """
    If advisor produced a focus → tactical planner.
    If advisor skipped (nothing viable) → phase is done → merge_knowledge.
    """
    if state.get("vuln_focus"):
        return "tactical"
    return "merge_knowledge"


# ============= Graph Construction =============

flow = StateGraph(MasterState)

flow.add_node("strategic",       strategic_planner)
flow.add_node("vuln_advisor",    vuln_advisor)
flow.add_node("tactical",        tactical_planner)
flow.add_node("execute",         execute_node)
flow.add_node("merge_knowledge", merge_knowledge_node)

flow.add_edge(START, "strategic")

flow.add_conditional_edges(
    "strategic",
    route_after_strategic,
    {"vuln_advisor": "vuln_advisor", "tactical": "tactical", "end": END},
)

flow.add_conditional_edges(
    "vuln_advisor",
    route_after_advisor,
    {"tactical": "tactical", "merge_knowledge": "merge_knowledge"},
)

flow.add_conditional_edges(
    "tactical",
    route_after_tactical,
    {"execute": "execute", "vuln_advisor": "vuln_advisor", "merge_knowledge": "merge_knowledge"},
)

flow.add_edge("execute", "tactical")
flow.add_edge("merge_knowledge", "strategic")

graph = flow.compile()


# ============= Entry Point =============

def run_pentest(query: str, max_global_iterations: int = 150, verbose: bool = True) -> dict:
    """
    Run the full dual-planner pentest orchestration.

    Args:
        query: Penetration testing objective
        max_global_iterations: LangGraph recursion limit (total node visits
            across both planners, executions, and merges)
        verbose: log progress

    Returns:
        Dict with:
            - final_answer: str
            - knowledge: TargetKnowledge (final knowledge graph)
            - phase_history: List[PhaseHistoryRecord]
            - execution_history: List[Dict[str, str]]
    """
    if verbose:
        logger.info(f"OBJECTIVE: {query}")

    state: MasterState = {
        "query": query,
        "current_phase": "",
        "phase_objective": "",
        "phase_iteration_count": 0,
        "knowledge": void_knowledge(),
        "plan": [],
        "execution_history": [],
        "phase_history": [],
        "_phase_summary": "",
        "_extracted_knowledge": void_knowledge(),
        "vuln_focus":    None,
        "checked_vulns": [],
        "final_answer": "",
        "thinking": "",
    }

    result = graph.invoke(state, config={"recursion_limit": max_global_iterations})

    if verbose:
        logger.info(f"FINAL ANSWER:\n{result.get('final_answer', '')}")

    return {
        "final_answer": result.get("final_answer", ""),
        "knowledge": result.get("knowledge", void_knowledge()),
        "phase_history": result.get("phase_history", []),
        "execution_history": result.get("execution_history", []),
    }


if __name__=="__main__":
    print("starting test-1")
    result=run_pentest(query="this is the ip: 10.49.158.80")
    print("result: ", result)