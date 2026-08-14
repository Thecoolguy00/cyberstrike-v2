"""Migrated, scoped tactical extractor for attack sessions (V4)."""

import hashlib
from functools import lru_cache
from typing import Dict, List

from app.utilities import dc_logger
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

from prototype.sub_agents.helper import extract_json_block
from prototype.ver4.schemas import CoverageKeys, DiscoveryKnowledge, Finding, TacticalExtraction

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))


@lru_cache(maxsize=1)
def _extractor_parser() -> PydanticOutputParser:
    return PydanticOutputParser(pydantic_object=TacticalExtraction)


def _extractor_llm():
    """Lazy import + construction: avoids pulling ver3 LLM deps at import time."""
    from app.utilities.llm_helper import LLMHelper
    return LLMHelper.get_llm_for_service("tactical_extractor")


def _finding_id(finding_type: str, location: str) -> str:
    return hashlib.md5(f"{finding_type}|{location}".encode("utf-8")).hexdigest()[:12]


def update_coverage_from_results(knowledge: DiscoveryKnowledge, results: List[Dict]) -> None:
    for result in results:
        if result.get("status") == "SUCCESS" and result.get("coverage_keys"):
            for key in result["coverage_keys"]:
                entry = knowledge.coverage.setdefault("attack_analysis", {}).setdefault(key, {"required": True, "completed": False})
                entry["completed"] = True


def register_dynamic_attack_coverage(knowledge: DiscoveryKnowledge) -> None:
    cov = knowledge.coverage.setdefault("attack_analysis", {})
    if any(
        any(token in endpoint.url.lower() for token in ("login", "signin", "auth", "session"))
        for endpoint in knowledge.endpoints.values()
    ):
        cov.setdefault(CoverageKeys.AUTH_LOGIN, {"required": True, "completed": False})
    input_values = list(knowledge.inputs.values())
    if any(
        any(token in (item.param or "").lower() for token in ("id", "uid", "user", "account", "uuid"))
        for item in input_values
    ):
        cov.setdefault(CoverageKeys.IDOR_NUMERIC, {"required": True, "completed": False})
    if input_values:
        cov.setdefault(CoverageKeys.DOM_XSS, {"required": True, "completed": False})


def _extract_via_llm(knowledge: DiscoveryKnowledge, results: List[Dict]) -> List[Finding]:
    if not results:
        return []
    results_str = "\n\n".join(
        f"[{result.get('agent')}] Task: {result.get('task', '')}\nResult:\n{str(result.get('result', ''))[:2000]}"
        for result in results
    )
    existing = "\n".join(
        f"  - {f.severity}: {f.type} at {f.location}"
        for f in knowledge.findings.values()
    ) or "  - none"
    system_prompt = f"""You are a structured knowledge extractor for ONE scoped attack session.

From the raw agent output below, extract ONLY NEW findings — do not re-list findings already present.

Extract things that are confirmed or strongly indicated: vulnerable params, injection points, misconfigurations,
header issues, exposed files, secrets, or confirmed CVEs. Ignore noise and scan progress lines.

CURRENT FINDINGS (do NOT duplicate these):
{existing}

OUTPUT FORMAT:
{_extractor_parser().get_format_instructions()}
"""
    user_prompt = f"""Execution results from this batch:

{results_str}

Extract only NEW findings.
"""
    response = _extractor_llm().invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        config={"run_name": "V4 Scoped Extractor LLM"},
    )
    parsed: TacticalExtraction = _extractor_parser().parse(extract_json_block(response.content))
    return parsed.findings


def extract_results(knowledge: DiscoveryKnowledge, results: List[Dict]) -> bool:
    """
    Apply one execution batch to the knowledge graph.

    Returns True when meaningful progress was made (new findings or intel added),
    so the session loop can track stuck cycles.
    """
    progress = False

    for result in results:
        if result.get("agent") == "intel_a":
            from prototype.ver4.intelligence import _apply_intel_result
            if _apply_intel_result(knowledge, result.get("result", "")):
                progress = True

    update_coverage_from_results(knowledge, results)
    register_dynamic_attack_coverage(knowledge)

    findings: List[Finding] = []
    try:
        findings = _extract_via_llm(knowledge, results)
    except Exception as exc:
        logger.error(f"[attack.extractor] Extraction failed (skipping): {exc}")

    for finding in findings:
        # The LLM's structured output may fabricate an id — override with a
        # deterministic one. timestamp is not part of the schema.
        finding_id = _finding_id(finding.type, finding.location)
        finding.id = finding_id
        if finding_id not in knowledge.findings:
            knowledge.findings[finding_id] = finding
            progress = True
    return progress