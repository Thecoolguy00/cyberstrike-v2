"""Scoped attack session orchestration.

Runs the migrated tactical loop (Strategic -> Tactical -> Agents -> Extractor)
against ONE confirmed web target, bounded by iteration and stuck-cycle caps.
"""

from typing import Dict, Optional

from app.utilities import dc_logger

from prototype.ver4.attack.extractor import extract_results, register_dynamic_attack_coverage
from prototype.ver4.attack.strategic import resolve_attack_objective
from prototype.ver4.attack.tactical import tactical_planner
from prototype.ver4.constants import MAX_ATTACK_SESSION_ITERATIONS, MAX_STUCK_CYCLES
from prototype.ver4.schemas import AttackSession, DiscoveryKnowledge

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))


def _session_state(
    knowledge: DiscoveryKnowledge,
    query: str,
    objective: str,
    target: str,
    history: list,
    metrics: Optional[Dict] = None,
) -> Dict:
    return {
        "query": query,
        "target": target,
        "objective": objective,
        "knowledge": knowledge,
        "execution_history": history,
        "phase": "attack_analysis",
        "metrics": metrics or {},
    }


async def run_attack_session(
    knowledge: DiscoveryKnowledge,
    target: str,
    query: str,
    metrics: Optional[Dict] = None,
    verbose: bool = True,
) -> AttackSession:
    """Attack one confirmed web target. Mutates `knowledge` in place."""
    objective = resolve_attack_objective(query, knowledge, target)
    session = AttackSession(target=target, objective=objective)
    history = []
    stuck = 0

    for iteration in range(MAX_ATTACK_SESSION_ITERATIONS):
        state = _session_state(knowledge, query, objective, target, history, metrics)
        plan = tactical_planner(state)

        if not plan.plan:
            session.summary = plan.phase_summary or "Attack session complete: no further tasks."
            session.iterations = iteration + 1
            break

        tasks = [task.model_dump() for task in plan.plan]

        # Lazy import: executor pulls in the agent graphs which connect to MCP.
        from prototype.sub_agents.executor import execute_plan_parallel

        results = await execute_plan_parallel(tasks, verbose=verbose)
        history.extend(results)

        progress = extract_results(knowledge, results)
        session.iterations = iteration + 1

        if not progress:
            stuck += 1
            if metrics is not None:
                metrics["stuck_events"] = metrics.get("stuck_events", 0) + 1
            if stuck >= MAX_STUCK_CYCLES:
                session.summary = "Attack session ended: no meaningful progress across consecutive cycles."
                break
        else:
            stuck = 0
    else:
        session.summary = "Attack session reached the iteration cap."

    session.executions_consumed = len(history)
    session.completed = True
    register_dynamic_attack_coverage(knowledge)
    logger.info(f"[attack.session] {target}: {session.iterations} cycles, {session.executions_consumed} executions -> {session.summary}")
    return session