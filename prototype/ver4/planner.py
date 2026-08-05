"""V4 entry point: deterministic discovery first, legacy planner second."""

from typing import Any, Dict, Optional

from prototype.sub_agents.schemas import void_knowledge
from prototype.ver4.adapter import to_legacy_knowledge, to_planner_input
from prototype.ver4.discovery.orchestrator import run_discovery
from prototype.ver4.runtime.base import DiscoveryRuntime
from prototype.ver4.schemas import DiscoveryBudget, PlannerInput


def _initial_state(target: str, planner_input: PlannerInput) -> Dict[str, Any]:
    knowledge = to_legacy_knowledge(planner_input)
    return {
        "query": target,
        "current_phase": "",
        "phase_objective": "",
        "phase_iteration_count": 0,
        "knowledge": knowledge,
        "plan": [],
        "execution_history": [],
        "last_execution_results": [],
        "phase_history": [],
        "_phase_summary": "Deterministic V4 discovery completed before planning.",
        "_extracted_knowledge": void_knowledge(),
        "vuln_nudge": None,
        "checked_vulns": [],
        "final_answer": "",
        "last_node": "deterministic_discovery",
        "metrics": {"cycles": 0, "reviewer_edits": 0, "coverage_completed": 0, "duplicate_tasks_removed": 0, "intel_tasks": 0, "stuck_events": 0, "strategic_invocations": 0},
    }


async def run_v4(target: str, runtime: Optional[DiscoveryRuntime] = None, budget: Optional[DiscoveryBudget] = None, run_planner: bool = True) -> Dict[str, Any]:
    discovery = await run_discovery(target, runtime=runtime, budget=budget)
    planner_input = to_planner_input(discovery)
    if not run_planner:
        return {"discovery": discovery, "planner_input": planner_input}
    from prototype.sub_agents.master_graph import graph
    result = graph.invoke(_initial_state(target, planner_input), config={"recursion_limit": 200})
    return {"discovery": discovery, "planner_input": planner_input, "planner_result": result}
