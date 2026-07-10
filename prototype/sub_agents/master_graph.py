# master_graph.py
"""
Master orchestration graph.

Key changes vs previous version
────────────────────────────────
1. vuln_advisor runs EVERY cycle across ALL phases (not only vuln_analysis).
   Graph flow: strategic → advisor → tactical → execute → advisor → tactical …
   The advisor is now a nudge layer, not a gate.

2. execute_node uses the new parallel executor.
   Independent tasks in a plan batch run concurrently via asyncio.gather.

3. route_after_tactical no longer handles checked_vulns marking.
   That responsibility moved into tactical_planner itself (cleaner ownership).

4. merge_knowledge_node unchanged in logic but records executions_consumed
   correctly using the PhaseHistoryRecord.
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
from prototype.sub_agents.tactical_planner_module  import tactical_planner
from prototype.sub_agents.vuln_advisor             import vuln_advisor
from prototype.sub_agents.executor                 import execute_plan

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))
load_dotenv()


# ─── Nodes ────────────────────────────────────────────────────────────────────

def execute_node(state: MasterState) -> dict:
    """Run the current plan via the parallel executor."""
    executions = execute_plan(state.get("plan", []), verbose=True)
    return {
        **state,
        "execution_history": state.get("execution_history", []) + executions,
        "plan": [],
    }


def merge_knowledge_node(state: MasterState) -> dict:
    """
    Finalise a completed phase:
    - merge extracted knowledge into the master graph
    - append a PhaseHistoryRecord
    - clear handoff fields
    """
    phase_history    = state.get("phase_history", [])
    consumed_so_far  = sum(rec.get("executions_consumed", 0) for rec in phase_history)
    total_executions = len(state.get("execution_history", []))
    executions_this_phase = total_executions - consumed_so_far

    record: PhaseHistoryRecord = {
        "phase":               state["current_phase"],
        "summary":             state.get("_phase_summary", ""),
        "iterations":          state.get("phase_iteration_count", 0),
        "executions_consumed": executions_this_phase,
    }

    merged = merge_knowledge(
        state.get("knowledge", void_knowledge()),
        state.get("_extracted_knowledge", void_knowledge()),
    )

    if state.get("_phase_summary"):
        logger.info(f"[phase complete] {state['current_phase']}: {state['_phase_summary']}")

    return {
        **state,
        "knowledge":            merged,
        "phase_history":        phase_history + [record],
        "_phase_summary":       "",
        "_extracted_knowledge": void_knowledge(),
        "vuln_nudge":           None,   # clear stale nudge on phase transition
    }


# ─── Routing ──────────────────────────────────────────────────────────────────

def route_after_strategic(state: MasterState) -> Literal["vuln_advisor", "end"]:
    """
    Strategic planner always hands off to advisor next.
    Advisor runs even for reporting (it will skip — cheap call).
    Exception: if final_answer is already set, we are done.
    """
    if state.get("final_answer"):
        return "end"
    return "vuln_advisor"


def route_after_advisor(state: MasterState) -> Literal["tactical", "merge_knowledge"]:
    """
    Advisor always feeds into tactical unless the phase has no agents at
    all (reporting), in which case we go straight to merge_knowledge so
    strategic can produce the final_answer.
    """
    from prototype.sub_agents.schemas import PHASE_AGENT_MAP
    phase = state.get("current_phase", "")
    if not PHASE_AGENT_MAP.get(phase):
        # reporting phase — no agents, let strategic synthesise
        return "merge_knowledge"
    return "tactical"


def route_after_tactical(state: MasterState) -> Literal["execute", "merge_knowledge"]:
    """
    - Non-empty plan → execute (parallel)
    - Empty plan     → phase is done → merge_knowledge
    - Iteration cap  → force merge_knowledge
    """
    if state.get("plan"):
        return "execute"

    iterations = state.get("phase_iteration_count", 0)
    if iterations >= MAX_PHASE_ITERATIONS and not state.get("_phase_summary"):
        logger.warning(
            f"[tactical] Phase '{state['current_phase']}' hit iteration cap "
            f"({MAX_PHASE_ITERATIONS}) — forcing advance"
        )
        # mutate in-place before returning (safe in LangGraph node routing)
        state["_phase_summary"] = (
            f"Phase '{state['current_phase']}' ended at iteration cap "
            f"({MAX_PHASE_ITERATIONS}) without an explicit completion signal."
        )

    return "merge_knowledge"


def route_after_execute(state: MasterState) -> Literal["vuln_advisor"]:
    """
    After execution always re-run the advisor so it can update its nudge
    based on the latest results before tactical plans the next cycle.
    This is the key change: advisor → tactical → execute → advisor loop.
    """
    return "vuln_advisor"


# ─── Graph construction ───────────────────────────────────────────────────────

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
    {"vuln_advisor": "vuln_advisor", "end": END},
)

flow.add_conditional_edges(
    "vuln_advisor",
    route_after_advisor,
    {"tactical": "tactical", "merge_knowledge": "merge_knowledge"},
)

flow.add_conditional_edges(
    "tactical",
    route_after_tactical,
    {"execute": "execute", "merge_knowledge": "merge_knowledge"},
)

# After execute: always back to advisor (not directly to tactical)
flow.add_conditional_edges(
    "execute",
    route_after_execute,
    {"vuln_advisor": "vuln_advisor"},
)

flow.add_edge("merge_knowledge", "strategic")

graph = flow.compile()


# ─── Entry point ──────────────────────────────────────────────────────────────

def run_pentest(query: str, max_global_iterations: int = 200, verbose: bool = True) -> dict:
    if verbose:
        logger.info(f"OBJECTIVE: {query}")

    state: MasterState = {
        "query":                 query,
        "current_phase":         "",
        "phase_objective":       "",
        "phase_iteration_count": 0,
        "knowledge":             void_knowledge(),
        "plan":                  [],
        "execution_history":     [],
        "phase_history":         [],
        "_phase_summary":        "",
        "_extracted_knowledge":  void_knowledge(),
        "vuln_nudge":            None,
        "checked_vulns":         [],
        "final_answer":          "",
        "thinking":              "",
    }

    result = graph.invoke(state, config={"recursion_limit": max_global_iterations})

    if verbose:
        logger.info(f"FINAL ANSWER:\n{result.get('final_answer', '')}")

    return {
        "final_answer":      result.get("final_answer",      ""),
        "knowledge":         result.get("knowledge",         void_knowledge()),
        "phase_history":     result.get("phase_history",     []),
        "execution_history": result.get("execution_history", []),
    }


if __name__ == "__main__":
    print("starting test-1")
    result = run_pentest(query="this is the ip: 10.49.158.80")
    print("result:", result)