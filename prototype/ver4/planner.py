"""V4 entry point: deterministic discovery (L1/L2) + Layer-2 decision loop.

No legacy ver3 master_graph / strategic planner in this path.
"""

from typing import Any, Dict, List, Optional

from app.utilities import dc_logger

from prototype.ver4.adapter import to_planner_input
from prototype.ver4.constants import MAX_DECISION_ITERATIONS
from prototype.ver4.decision.llm import decide_with_llm
from prototype.ver4.decision.rules import rule_decision
from prototype.ver4.discovery.orchestrator import run_discovery
from prototype.ver4.report import build_report
from prototype.ver4.runtime.base import DiscoveryRuntime
from prototype.ver4.schemas import DecisionAction, DiscoveryBudget, PlannerDecision

# Import the executor eagerly here. It pulls in the sub_agents agent graphs,
# which call asyncio.run(get_mcp_tools()) at import time; that must happen in a
# synchronous context (module load) — not inside the running discovery loop.
from prototype.sub_agents.executor import execute_plan_parallel  # noqa: E402,F401

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))


def _empty_metrics() -> Dict[str, int]:
    return {
        "cycles": 0,
        "llm_decisions": 0,
        "intel_tasks": 0,
        "enrichments": 0,
        "attack_sessions": 0,
        "stuck_events": 0,
        "reports": 0,
    }


def _decision_repeats_last(history: List[PlannerDecision], decision: PlannerDecision) -> bool:
    if not history:
        return False
    previous = history[-1]
    return previous.action == decision.action and (previous.target or "?") == (decision.target or "?")


async def run_v4(
    target: str,
    runtime: Optional[DiscoveryRuntime] = None,
    budget: Optional[DiscoveryBudget] = None,
    run_planner: bool = True,
    ports: Optional[List[str]] = None,
) -> Dict[str, Any]:
    discovery = await run_discovery(target, runtime=runtime, budget=budget, ports=ports)
    if not run_planner:
        return {"discovery": discovery, "planner_input": to_planner_input(discovery)}

    from prototype.ver4.intelligence import run_exploit_intel

    metrics = _empty_metrics()
    decision_history: List[PlannerDecision] = []
    final_answer = ""
    full_scan_done = bool(discovery.coverage.get("recon", {}).get("network_l2", {}).get("completed"))

    # Exploit intel runs right after Discovery L1 (and again after L2 below).
    metrics["intel_tasks"] += await run_exploit_intel(discovery)

    for iteration in range(MAX_DECISION_ITERATIONS):
        metrics["cycles"] = iteration + 1
        decision = rule_decision(discovery, full_scan_done)
        if decision is None:
            decision = decide_with_llm(discovery, target, decision_history)
            metrics["llm_decisions"] += 1

        if _decision_repeats_last(decision_history, decision):
            logger.info(f"[v4] Suppressing repeat decision {decision.action.value} {decision.target or ''}")
            decision = PlannerDecision(
                action=DecisionAction.REPORT,
                rationale="Previous decision repeated with no new evidence; moving to report.",
            )

        decision_history.append(decision)
        logger.info(f"[v4] iteration {iteration + 1}: {decision.action.value} {decision.target or ''} — {decision.rationale}")

        if decision.action == DecisionAction.NETWORK_L2:
            if full_scan_done:
                continue  # no-op; next cycle the rules route to REPORT
            discovery = await run_discovery(target, level=2, runtime=runtime, budget=budget, knowledge=discovery)
            full_scan_done = True
            metrics["intel_tasks"] += await run_exploit_intel(discovery)
            continue

        if decision.action == DecisionAction.ATTACK:
            from prototype.ver4.attack.session import run_attack_session
            await run_attack_session(discovery, decision.target, target, metrics)
            metrics["attack_sessions"] += 1
            continue

        # REPORT
        final_answer = build_report(discovery)
        metrics["reports"] += 1
        break
    else:
        # Decision cap reached without a REPORT decision.
        final_answer = build_report(discovery)
        metrics["reports"] += 1

    return {
        "discovery": discovery,
        "planner_input": to_planner_input(discovery),
        "report": final_answer,
        "decision_history": [decision.model_dump(mode="json") for decision in decision_history],
        "metrics": metrics,
    }