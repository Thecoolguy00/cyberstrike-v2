"""LLM-backed decision path — called only when deterministic rules find meaningful evidence."""

from functools import lru_cache
from typing import List

from app.utilities import dc_logger
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

from prototype.sub_agents.helper import extract_json_block
from prototype.ver4.decision.prompts import get_decision_system_prompt, get_decision_user_prompt
from prototype.ver4.decision.rules import confirmed_web_targets, has_web_evidence
from prototype.ver4.schemas import DecisionAction, DiscoveryKnowledge, PlannerDecision

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))


@lru_cache(maxsize=1)
def _decision_parser() -> PydanticOutputParser:
    return PydanticOutputParser(pydantic_object=PlannerDecision)


def _decision_llm():
    """Lazy import + construction: avoids pulling ver3 LLM deps at import time."""
    from app.utilities.llm_helper import LLMHelper
    return LLMHelper.get_llm_for_service("l2_decision")


def _fallback_decision(knowledge: DiscoveryKnowledge) -> PlannerDecision:
    targets = confirmed_web_targets(knowledge)
    if targets:
        return PlannerDecision(
            action=DecisionAction.ATTACK,
            target=targets[0],
            rationale="LLM decision failed; falling back to strongest confirmed web target.",
        )
    return PlannerDecision(
        action=DecisionAction.REPORT,
        rationale="LLM decision failed and no confirmed web target exists.",
    )


def decide_with_llm(
    knowledge: DiscoveryKnowledge,
    query: str,
    decision_history: List[PlannerDecision],
) -> PlannerDecision:
    """
    One strategic LLM call. Validates the output against confirmed targets and
    gating rules so a malformed reply degenerates into a safe deterministic fallback.
    """
    if not has_web_evidence(knowledge):
        return _fallback_decision(knowledge)

    confirmed = confirmed_web_targets(knowledge)
    messages = [
        SystemMessage(content=get_decision_system_prompt()),
        HumanMessage(content=get_decision_user_prompt(query, knowledge, decision_history)),
    ]
    try:
        response = _decision_llm().invoke(messages, config={"run_name": "V4 L2 Decision LLM"})
        decision = _decision_parser().parse(extract_json_block(response.content))
    except Exception as exc:
        logger.error(f"[l2_decision] LLM decision failed: {exc}")
        return _fallback_decision(knowledge)

    # Validate / sanitize
    if decision.action == DecisionAction.ATTACK:
        if decision.target not in confirmed:
            logger.warning(f"[l2_decision] Target {decision.target!r} not in confirmed targets {confirmed}")
            if confirmed:
                decision.target = confirmed[0]
            else:
                return PlannerDecision(action=DecisionAction.REPORT, rationale="ATTACK requested but no confirmed web target; reporting.")
    elif decision.action == DecisionAction.NETWORK_L2:
        decision.target = ""  # L2 only re-scans; no target
    else:
        decision.target = ""

    # Do not re-attack the same target twice.
    same_target_attacked = any(
        prior.action == DecisionAction.ATTACK and prior.target == decision.target
        for prior in decision_history
    )
    if decision.action == DecisionAction.ATTACK and same_target_attacked:
        return PlannerDecision(
            action=DecisionAction.REPORT,
            rationale=f"Target {decision.target} was already attacked; no new decision surface.",
        )

    return decision