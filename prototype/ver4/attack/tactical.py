"""Migrated, scoped tactical planner for attack sessions (V4, no recon gates)."""

import json
import re
from functools import lru_cache
from typing import Dict, List, Tuple

from app.utilities import dc_logger
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

from prototype.sub_agents.helper import extract_json_block
from prototype.ver4.attack.strategic import target_tokens
from prototype.ver4.constants import AGENT_TASK_PHASE_PREFIX
from prototype.ver4.schemas import Task, TacticalPlan

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))

ALLOWED_ATTACK_AGENTS = {"http_a", "ferox_a", "python_a", "xss_a", "intel_a"}
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.I)


@lru_cache(maxsize=1)
def _tactical_parser() -> PydanticOutputParser:
    return PydanticOutputParser(pydantic_object=TacticalPlan)


def _tactical_llm():
    """Lazy import + construction: avoids pulling ver3 LLM deps at import time."""
    from app.utilities.llm_helper import LLMHelper
    return LLMHelper.get_llm_for_service("tactical_planner")


def _knowledge_digest(state: Dict) -> str:
    knowledge = state["knowledge"]
    lines = []

    if knowledge.endpoints:
        lines.append(f"ENDPOINTS ({len(knowledge.endpoints)}):")
        for url in sorted(knowledge.endpoints)[:20]:
            lines.append(f"  {url}")
        if len(knowledge.endpoints) > 20:
            lines.append(f"  ... and {len(knowledge.endpoints) - 20} more")

    if knowledge.inputs:
        lines.append(f"INPUT POINTS ({len(knowledge.inputs)}):")
        for item in list(knowledge.inputs.values())[:20]:
            lines.append(f"  {item.url} param={item.param} method={item.method} type={item.input_type or '-'}")

    if knowledge.technologies:
        lines.append("TECHNOLOGIES:")
        for tech in knowledge.technologies.values():
            lines.append(f"  {tech.name} {tech.version or '(version unknown)'}")

    untested = [item for item in knowledge.exploit_intelligence.values() if item.cve and not item.tested]
    if untested:
        lines.append("UNTESTED CVEs:")
        for item in untested:
            lines.append(f"  {item.cve} ({item.technology} {item.version}) severity={item.severity}")
    else:
        lines.append("UNTESTED CVEs: none")

    if knowledge.findings:
        lines.append(f"FINDINGS SO FAR ({len(knowledge.findings)}):")
        for finding in list(knowledge.findings.values())[:20]:
            lines.append(f"  {finding.severity}: {finding.type} at {finding.location} confirmed={finding.confirmed}")

    return "\n".join(lines)


def filter_task_list(tasks: List[Task], state: Dict) -> Tuple[List[Task], int, int]:
    """Agent allowlist + target token allowlist + description dedup (vs batch & history)."""
    tokens = [token.lower() for token in target_tokens(state["target"])]
    history_descs = {str(entry.get("task", "")).lower() for entry in state.get("execution_history", [])}
    kept: List[Task] = []
    seen_descs = set()
    agent_dropped = 0
    target_dropped = 0
    duplicate_dropped = 0
    for task in tasks:
        if task.agent not in ALLOWED_ATTACK_AGENTS:
            agent_dropped += 1
            continue
        desc_lower = task.task_description.lower()
        if not tokens or not any(token in desc_lower for token in tokens):
            target_dropped += 1
            continue
        if desc_lower in seen_descs or desc_lower in history_descs:
            duplicate_dropped += 1
            continue
        seen_descs.add(desc_lower)
        kept.append(task)
    return kept, agent_dropped + target_dropped + duplicate_dropped, target_dropped


def cve_verification_tasks(state: Dict) -> List[Task]:
    """
    Auto-inject verification tasks for untested CVEs — but ONLY for technologies
    that are part of the scoped web target's stack. This stops SSH/RTSP/mislabelled
    intel CVEs from being verified against the web application being attacked.
    """
    knowledge = state["knowledge"]
    target = state["target"]
    history_descs = {str(entry.get("task", "")).lower() for entry in state.get("execution_history", [])}

    web_tech = {name.strip().lower() for name in knowledge.technologies}
    tasks: List[Task] = []
    for key, item in sorted(knowledge.exploit_intelligence.items()):
        if not item.cve or item.tested:
            continue
        if item.technology.strip().lower() not in web_tech:
            continue  # non-web (or unrecognised) service — leave verification to a dedicated session
        for cve_id in CVE_RE.findall(item.cve):
            scope = item.location or target
            description = f"{AGENT_TASK_PHASE_PREFIX} Verify vulnerability {cve_id} for {item.technology} {item.version} on {scope}"
            if description.lower() in history_descs:
                continue
            key_slug = re.sub(r"[^a-zA-Z0-9_]", "_", key).lower()
            tasks.append(Task(
                agent="python_a",
                task_description=description,
                task_id=f"cve_verify_{cve_id.replace('-', '_')}_{key_slug}",
                depends_on=[],
                coverage_keys=["cve.verification"],
            ))
            # Mark as tested once a verification task is dispatched.
            item.tested = True
    return tasks


def _tactical_system_prompt(state: Dict) -> str:
    return f"""You are a tactical task planner for ONE scoped attack session (internal phase: attack_analysis).

SCOPE: {state['target']} ONLY. Every task_description MUST include the target URL/host
AND start with the prefix "{AGENT_TASK_PHASE_PREFIX}" (this is the agent-recognized testing phase).

SESSION OBJECTIVE:
{state['objective']}

PRIORITY:
1. User-requested vulnerability type (see objective).
2. Test known CVEs listed as UNTESTED — schedule verification tasks.
3. Input-based testing (XSS via xss_a; SQLi / template / command injection via http_a / python_a).
4. Endpoint-based checks (backup files, source disclosure, directory listing via ferox_a / http_a).
5. Configuration checks (CORS, clickjacking, cookie flags, secret leaks in JS/bodies).

AGENTS AVAILABLE:
- http_a  — HTTP requests: any method, headers, cookies, JSON/form/raw bodies, presets (browser/api/webdav)
- ferox_a — directory and file enumeration on confirmed web services
- python_a— write and execute custom Python scripts (research, validation, custom payload handling)
- xss_a   — XSS payload injection and detection (dalfox / xsstrike)
- intel_a — exploit intelligence lookups (normally scheduled automatically; use sparingly)

RULES:
- The knowledge graph is the source of truth; only interact with the scoped target.
- Never repeat work already in EXECUTION HISTORY.
- Batch truly independent tasks with empty depends_on; use depends_on for real ordering.
- Only plan tasks that are executable right now.
- EXECUTION CONSTRAINT: at most 5 agent tasks run CONCURRENTLY. Keep each cycle's
  independent batch lean and prioritized — never dump an oversized one-shot batch;
  that only serializes against the 5-task limit and wastes tokens.
- When the objective is complete, return an EMPTY plan and a phase_summary.

OUTPUT FORMAT:
{_tactical_parser().get_format_instructions()}
"""


def _tactical_user_prompt(state: Dict) -> str:
    history = state.get("execution_history", [])
    if history:
        history_str = "\n".join(
            f"{i}. [{entry.get('agent')}] {entry.get('task', '')}\n   -> {str(entry.get('result', ''))[:300]}"
            for i, entry in enumerate(history[-10:], 1)
        )
    else:
        history_str = "None yet — first planning cycle for this session."

    return f"""ORIGINAL QUERY:
{state['query']}

SESSION OBJECTIVE:
{state['objective']}

SCOPE: {state['target']}

EXECUTION HISTORY (this session):
{history_str}

KNOWLEDGE SNAPSHOT:
{_knowledge_digest(state)}

Output the FULL batch of tasks for this cycle, prefixed with "{AGENT_TASK_PHASE_PREFIX}".
"""


def tactical_planner(state: Dict) -> TacticalPlan:
    messages = [
        SystemMessage(content=_tactical_system_prompt(state)),
        HumanMessage(content=_tactical_user_prompt(state)),
    ]
    try:
        response = _tactical_llm().invoke(messages, config={"run_name": "V4 Scoped Tactical Planner LLM"})
        parsed: TacticalPlan = _tactical_parser().parse(extract_json_block(response.content))
    except Exception as exc:
        logger.error(f"[attack.tactical] Planner failed: {exc}")
        return TacticalPlan(plan=[], phase_summary=f"Attack session ended due to planner error: {exc}")

    filtered, dropped, off_target = filter_task_list(parsed.plan, state)
    if dropped:
        logger.info(f"[attack.tactical] Filtered {dropped} out-of-scope/duplicate task(s) "
                    f"({off_target} off-target, rest agent-blocked/duplicates)")

    cve_tasks = cve_verification_tasks(state)
    seen_ids = set()
    merged: List[Task] = []
    for task in cve_tasks + filtered:
        if task.task_id not in seen_ids:
            seen_ids.add(task.task_id)
            merged.append(task)

    return TacticalPlan(plan=merged, phase_summary=parsed.phase_summary)