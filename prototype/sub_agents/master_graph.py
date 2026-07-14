# master_graph.py
"""
Master orchestration graph.

Graph flow
──────────
strategic → tactical_planner → execute → tactical_extractor → vuln_advisor → tactical_planner → execute …
                                                                                  ↓
                                                                          merge_knowledge → strategic

Key design decisions
────────────────────
1. strategic goes directly to tactical_planner on each new phase (no advisor on cycle 1).
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
from prototype.sub_agents.tactical_planner_module  import tactical_planner, tactical_extractor
from prototype.sub_agents.plan_reviewer             import plan_reviewer
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
        "last_execution_results": executions,
        "plan": [],
        "last_node": "execute",
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
        "last_node":            "merge_knowledge",  # reset last_node flag for the next phase
    }


# ─── Routing ──────────────────────────────────────────────────────────────────

def phase_complete(state: MasterState) -> bool:
    phase = state.get("current_phase")
    knowledge = state.get("knowledge", void_knowledge())
    coverage = knowledge.get("coverage", {}).get(phase, {})
    if not coverage:
        # If no coverage defined for phase, it's complete
        return True
    # If any required check is not completed, phase is not complete
    for check_id, check_val in coverage.items():
        if check_val.get("required") and not check_val.get("completed"):
            return False
    return True


def route_after_strategic(state: MasterState) -> Literal["tactical_planner", "end"]:
    if state.get("final_answer"):
        return "end"
    return "tactical_planner"


def route_after_reviewer(state: MasterState) -> Literal["execute", "merge_knowledge"]:
    """
    - Non-empty plan → execute
    - Empty plan or Iteration cap → merge_knowledge
    """
    if state.get("plan"):
        return "execute"

    iterations = state.get("phase_iteration_count", 0)
    if iterations >= MAX_PHASE_ITERATIONS and not state.get("_phase_summary"):
        logger.warning(
            f"[reviewer] Phase '{state['current_phase']}' hit iteration cap "
            f"({MAX_PHASE_ITERATIONS}) — forcing advance"
        )
        state["_phase_summary"] = (
            f"Phase '{state['current_phase']}' ended at iteration cap "
            f"({MAX_PHASE_ITERATIONS}) without an explicit completion signal."
        )

    return "merge_knowledge"


MAX_STUCK_CYCLES = 3


def route_after_extractor(state: MasterState) -> Literal["tactical_planner", "merge_knowledge"]:
    """
    Check if the phase has met all its coverage goals or is stuck.
    """
    if phase_complete(state):
        return "merge_knowledge"
    
    if state.get("stuck_cycle_count", 0) >= MAX_STUCK_CYCLES:
        logger.warning(
            f"[master_graph] Phase '{state['current_phase']}' hit MAX_STUCK_CYCLES ({MAX_STUCK_CYCLES}) — forcing advance"
        )
        return "merge_knowledge"
        
    return "tactical_planner"


# ─── Graph construction ───────────────────────────────────────────────────────

flow = StateGraph(MasterState)

flow.add_node("strategic",          strategic_planner)
flow.add_node("plan_reviewer",      plan_reviewer)
flow.add_node("tactical_planner",   tactical_planner)
flow.add_node("tactical_extractor", tactical_extractor)
flow.add_node("execute",            execute_node)
flow.add_node("merge_knowledge",    merge_knowledge_node)

flow.add_edge(START, "strategic")

flow.add_conditional_edges(
    "strategic",
    route_after_strategic,
    {"tactical_planner": "tactical_planner", "end": END},
)

# tactical_planner goes straight to reviewer
flow.add_edge("tactical_planner", "plan_reviewer")

# reviewer routes to execute or merge_knowledge
flow.add_conditional_edges(
    "plan_reviewer",
    route_after_reviewer,
    {"execute": "execute", "merge_knowledge": "merge_knowledge"},
)

flow.add_edge("execute", "tactical_extractor")

# after extraction, check if phase is complete
flow.add_conditional_edges(
    "tactical_extractor",
    route_after_extractor,
    {"tactical_planner": "tactical_planner", "merge_knowledge": "merge_knowledge"},
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
        "last_execution_results": [],
        "phase_history":         [],
        "_phase_summary":        "",
        "_extracted_knowledge":  void_knowledge(),
        "vuln_nudge":            None,
        "checked_vulns":         [],
        "final_answer":          "",
        "thinking":              "",
        "last_node":             "",
        "metrics": {
            "cycles": 0,
            "reviewer_edits": 0,
            "coverage_completed": 0,
            "duplicate_tasks_removed": 0,
            "intel_tasks": 0,
            "stuck_events": 0,
            "strategic_invocations": 0
        },
    }

    result = graph.invoke(state, config={"recursion_limit": max_global_iterations})

    if verbose:
        logger.info(f"FINAL ANSWER:\n{result.get('final_answer', '')}")
        m = result.get("metrics", {})
        logger.info(
            f"\n=== PENTEST METRICS ===\n"
            f"Cycles: {m.get('cycles', 0)}\n"
            f"Coverage Completed: {m.get('coverage_completed', 0)}\n"
            f"Reviewer edits: {m.get('reviewer_edits', 0)}\n"
            f"Intel tasks: {m.get('intel_tasks', 0)}\n"
            f"Strategic calls: {m.get('strategic_invocations', 0)}\n"
            f"Duplicate prevention: {m.get('duplicate_tasks_removed', 0)}\n"
            f"Stuck events: {m.get('stuck_events', 0)}\n"
            f"======================="
        )

    return {
        "final_answer":      result.get("final_answer",      ""),
        "knowledge":         result.get("knowledge",         void_knowledge()),
        "phase_history":     result.get("phase_history",     []),
        "execution_history": result.get("execution_history", []),
        "metrics":           result.get("metrics",           {}),
    }


if __name__ == "__main__":
    print("starting test-1")
    result = run_pentest(query="target ip: 10.48.152.206, focus on xss")
    print("result:", result)