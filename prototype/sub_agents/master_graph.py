# master_graph.py
"""
Master orchestration graph.

Graph flow
──────────
strategic → tactical → execute → vuln_advisor → tactical → execute → vuln_advisor …
                                                     ↓
                                             merge_knowledge → strategic

Key design decisions
────────────────────
1. strategic goes directly to tactical on each new phase (no advisor on cycle 1).
   The advisor would always skip on cycle 1 — the knowledge graph is empty at
   phase start. Skipping it saves one LLM call and moves the first real nudge
   one cycle earlier (advisor sees fresh _extracted_knowledge after the first
   execute, not the empty phase-start state).

2. vuln_advisor runs after every execute, when _extracted_knowledge is freshly
   populated by the preceding tactical call. The advisor reads
   merge(knowledge, _extracted_knowledge) so it sees the live state.

3. execute_node uses the parallel executor.
   Independent tasks in a plan batch run concurrently via asyncio.gather.

4. route_after_tactical no longer handles checked_vulns marking.
   That responsibility moved into tactical_planner itself (cleaner ownership).

5. merge_knowledge_node records executions_consumed via PhaseHistoryRecord.
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
        "post_execution": True,
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
        "_extracted_knowledge": void_knowledge(),  # intentional: resets the per-phase accumulator now that it's committed to knowledge
        "vuln_nudge":           None,   # clear stale nudge on phase transition
        "post_execution":       False,  # reset post_execution flag for the next phase
    }


# ─── Routing ──────────────────────────────────────────────────────────────────

def route_after_strategic(state: MasterState) -> Literal["tactical", "end"]:
    """
    Strategic planner hands off directly to tactical.

    Skipping the advisor on the first call of each phase is intentional:
    the knowledge graph is empty at phase start, so the advisor would
    always skip — wasting one LLM call. The advisor picks up on the loop
    after the first execute, when _extracted_knowledge is freshly populated.

    Exception: if final_answer is already set, the pentest is done.
    """
    if state.get("final_answer"):
        return "end"
    return "tactical"


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


def route_after_tactical(state: MasterState) -> Literal["execute", "vuln_advisor", "merge_knowledge"]:
    """
    - Non-empty plan → execute (if post_execution is False) or vuln_advisor (if post_execution is True)
    - Empty plan     → phase is done → merge_knowledge
    - Iteration cap  → force merge_knowledge
    """
    if state.get("plan"):
        if state.get("post_execution"):
            return "vuln_advisor"
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


# ─── Graph construction ───────────────────────────────────────────────────────

flow = StateGraph(MasterState)

flow.add_node("strategic",       strategic_planner)
flow.add_node("vuln_advisor",    vuln_advisor)
flow.add_node("tactical",        tactical_planner)
flow.add_node("execute",         execute_node)
flow.add_node("merge_knowledge", merge_knowledge_node)

flow.add_edge(START, "strategic")

# strategic → tactical directly (advisor has nothing to see on an empty KG)
flow.add_conditional_edges(
    "strategic",
    route_after_strategic,
    {"tactical": "tactical", "end": END},
)

flow.add_conditional_edges(
    "tactical",
    route_after_tactical,
    {"execute": "execute", "vuln_advisor": "vuln_advisor", "merge_knowledge": "merge_knowledge"},
)

# After execute: go back to tactical to extract results and plan the next batch
flow.add_edge("execute", "tactical")

flow.add_conditional_edges(
    "vuln_advisor",
    route_after_advisor,
    {"tactical": "tactical", "merge_knowledge": "merge_knowledge"},
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
        "post_execution":        False,
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
    result = run_pentest(query="target ip: 10.48.153.150, focus on xss")
    print("result:", result)