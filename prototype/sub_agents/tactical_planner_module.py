# tactical_planner_module.py
"""
Two-node tactical layer:

  tactical_extractor  — reads last_execution_results, extracts ONLY NEW
                        structured findings into _extracted_knowledge.
                        Small focused LLM call; no planning.

  tactical_planner    — reads the full knowledge graph (already updated by
                        extractor) + advisor nudge, outputs the next task
                        batch. No extraction.

Graph flow:
  strategic → tactical_planner → execute → tactical_extractor
           → vuln_advisor → tactical_planner → ...
           → merge_knowledge → strategic
"""

import asyncio
import json
from typing import Dict, List, Optional
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

from prototype.sub_agents.helper import extract_json_block
from app.utilities import dc_logger
from prototype.sub_agents.true_mcp_exec import run_mcp_tool
from app.utilities.llm_helper import LLMHelper
from prototype.sub_agents.schemas import (
    TacticalPlan,
    TacticalExtraction,
    MasterState,
    PHASE_AGENT_MAP,
    void_knowledge,
    VulnNudge,
    merge_knowledge,
)

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))
load_dotenv()

tactical_llm       = LLMHelper.get_llm_for_service("tactical_planner")
extractor_llm      = LLMHelper.get_llm_for_service("tactical_extractor")   # can be same or cheaper model
tactical_parser    = PydanticOutputParser(pydantic_object=TacticalPlan)
extractor_parser   = PydanticOutputParser(pydantic_object=TacticalExtraction)


# ─── Global rules + phase playbooks ─────────────────────────────────────────
# GLOBAL_RULES is injected into every phase prompt — keeps individual
# playbooks short and ensures consistent discipline across all phases.
# Each playbook covers ONE phase with a compact, state-based SOP.

GLOBAL_RULES = """
GLOBAL RULES
- The knowledge graph is the source of truth.
- Only interact with assets confirmed in the knowledge graph.
- Never repeat work already in the execution history.
- Only plan tasks that are executable right now.
- Batch independent tasks (empty depends_on = parallel).
- Return an empty plan when the phase objective is complete.
"""

RECON_PLAYBOOK = """
RECON

Objective
Discover reachable services and perform initial exploit research on identified technologies.

State

IF knowledge.open_ports is empty
→ Discover ports (nmap_a).

IF confirmed services or open ports exist but are not fingerprinted
→ Fingerprint them (nmap_a for version/banner, http_a GET/HEAD for HTTP confirmation only).

IF technology version or software details are discovered
→ Run exploit intelligence (intel_a) to check for known vulnerabilities and public exploits.

IF no ports are found open even after a full port scan
→ Finish phase.

Forbidden — HARD STOPS, no exceptions
- NO injection payloads of any kind: no XSS, SQLi, template injection, command injection,
  path traversal, or parameter fuzzing. This means no <script>, alert(), ', ", --, ;, ../
  in any request parameter — even "just to check reflection".
- NO endpoint enumeration (no ferox_a, no wordlist scanning, no directory brute-force).
- NO vulnerability testing of any kind. Exploit intelligence (intel_a) looks up public
  databases — it does NOT test the live target.
- http_a in this phase: GET and HEAD requests only, to confirm a port serves HTTP.
  Do NOT fuzz, probe, or send payloads.
"""

ENUMERATION_PLAYBOOK = """
ENUMERATION

Objective
Map web attack surface: find endpoints, parameters, forms, and allowed methods.

State

IF knowledge.web_services is empty
→ Finish phase immediately (nothing to enumerate).

IF endpoints are incomplete
→ Enumerate endpoints (ferox_a wordlist scan, http_a OPTIONS/PROPFIND).

IF input_points are incomplete
→ Inspect discovered endpoints for parameters and forms (http_a GET only).

IF attack surface is mapped
→ Finish phase.

Forbidden — HARD STOPS, no exceptions
- NO injection payloads of any kind: no XSS, SQLi, template injection, command injection,
  path traversal, or reflection probing. This means no <script>, alert(), ', ", --, ;, ../
  in any request parameter — even "just to see if it reflects".
- NO vulnerability testing. Discovery only.
- NO new port scanning or service fingerprinting (that was recon).
- http_a in this phase: GET, HEAD, OPTIONS, PROPFIND only.
  Do NOT send POST/PUT/PATCH/DELETE with payloads.
  Do NOT fuzz parameter values.
"""

VULN_ANALYSIS_PLAYBOOK = """
VULNERABILITY ANALYSIS

Objective
Identify vulnerabilities.

Priority

1. User-requested vulnerability type (check original query).
2. Exploit intelligence research for all newly discovered software versions, platforms, or custom services to check for known vulnerabilities and public exploits.
3. Input-based testing (XSS, SQLi, HTMLi, open redirect, IDOR).
4. Endpoint-based testing (backup files, source disclosure, directory listing).
5. Configuration checks (CORS, clickjacking, cookie flags, secret leaks).

Forbidden
- No exploitation.
- No new enumeration.
- No reconnaissance.
"""

EXPLOITATION_PLAYBOOK = """
EXPLOITATION

Objective
Confirm findings.

State

IF no findings
→ Finish phase.

IF findings remain unconfirmed
→ Confirm them with proof-of-concept.

IF multiple findings relate (same endpoint, session, user)
→ Attempt chaining.

Forbidden
- No destructive actions.
- No new discovery.
"""

REPORTING_PLAYBOOK = """
REPORTING

No agent execution.

Return:
- empty plan
- phase summary
- extracted knowledge
"""

TACTICAL_PHASE_PLAYBOOKS: Dict[str, str] = {
    "recon":         RECON_PLAYBOOK,
    "enumeration":   ENUMERATION_PLAYBOOK,
    "vuln_analysis": VULN_ANALYSIS_PLAYBOOK,
    "exploitation":  EXPLOITATION_PLAYBOOK,
    "reporting":     REPORTING_PLAYBOOK,
}


# ─── Nudge block injected into system prompt ──────────────────────────────────

# Nudge categories that involve active vulnerability testing / injection.
# These are NEVER permitted in recon or enumeration regardless of nudge priority.
_TESTING_NUDGE_IDS = {
    "user_intent_drift",
    "input_class_unchecked",
    "idor_unchecked",
    "clickjacking_unchecked",
    # any future injection-class nudge ids go here
}

# Phases in which active testing nudges are forbidden
_NO_TESTING_PHASES = {"recon", "enumeration"}


def _nudge_block(nudge: Optional[VulnNudge], allowed_agents: List[str], phase: str = "") -> str:
    """
    Render the advisor's VulnNudge as a prompt block.

    Phase gate enforced here as a second safety layer (the advisor already
    applies its own gate, but the tactical planner is the last line of defence):
    - Any testing/injection nudge is silently dropped in recon and enumeration.
    - Only discovery-class nudges (exploit intel, secret leak, dir listing)
      are forwarded in those early phases.
    """
    if not nudge or nudge.priority == "skip" or not nudge.vuln_id:
        return ""

    # Hard drop: testing nudges must never appear in early phases
    if phase in _NO_TESTING_PHASES and nudge.vuln_id.lower() in _TESTING_NUDGE_IDS:
        logger.warning(
            f"[tactical] Dropped '{nudge.vuln_id}' nudge in phase '{phase}' "
            f"— testing nudges are forbidden before vuln_analysis"
        )
        return ""

    valid_agents = [a for a in nudge.suggested_agents if a in allowed_agents]
    agents_str   = ", ".join(valid_agents) if valid_agents else "any available agent"
    targets_str  = "\n".join(f"  - {t}" for t in nudge.specific_targets) or "  - derive from knowledge graph"

    urgency = (
        "⚠ HIGH PRIORITY — address this before other tasks this cycle."
        if nudge.priority == "high"
        else "ℹ MEDIUM PRIORITY — fold into current work if it fits naturally."
    )

    return f"""
ADVISOR NUDGE ({nudge.priority.upper()})
  {urgency}
  Vulnerability:    {nudge.label} [{nudge.vuln_id}]
  Why now:          {nudge.rationale}
  Suggested agents: {agents_str}
  Targets:
{targets_str}

  HOW TO HANDLE:
  ⚠ IMPORTANT: The PHASE PLAYBOOK above is the primary authority.
    Only act on this nudge if it is permitted by the current phase.
    If the nudge asks for something the playbook forbids (e.g. injection
    testing during recon/enumeration), IGNORE this nudge entirely and
    follow the playbook instead.
  - If permitted and priority=high: include at least one task probing this
    in the plan with empty depends_on (runs in parallel).
  - If permitted and priority=medium: include if it fits; skip if plan full.
  - When you return an EMPTY plan (focus exhausted), set phase_summary and
    the graph will automatically mark "{nudge.vuln_id}" as checked.
"""


# ─── System prompt ────────────────────────────────────────────────────────────

def get_tactical_system_prompt(
    phase: str,
    phase_objective: str,
    nudge: Optional[VulnNudge] = None,
) -> str:
    allowed_agents = PHASE_AGENT_MAP.get(phase, [])
    agent_descriptions = {
        "nmap_a":   "nmap_a   — Network port and service discovery",
        "http_a":   "http_a   — Full HTTP agent: any method (GET/POST/PUT/DELETE/OPTIONS/"
                    "PROPFIND/PATCH), headers, cookies, JSON/form/raw body, presets "
                    "(browser/api/webdav). Use this for all HTTP interaction.",
        "ferox_a":  "ferox_a  — Directory and file enumeration on confirmed web services",
        "python_a": "python_a — Write and execute custom Python scripts for any task",
        "xss_a":    "xss_a    — XSS payload injection and detection",
        "intel_a":  "intel_a  — Exploit intelligence: searches Tavily, ExploitDB, GitHub, "
                    "and NVD for known CVEs and public PoCs for a given technology/version. "
                    "Use when a versioned service is identified. "
                    "Task format: 'Research <technology> <version> for known vulnerabilities'",
    }
    agent_lines = "\n".join(
        f"- {agent_descriptions[a]}" for a in allowed_agents if a in agent_descriptions
    ) or "- No agents available. Return empty plan + phase_summary immediately."

    playbook      = TACTICAL_PHASE_PLAYBOOKS.get(phase, "")
    nudge_section = _nudge_block(nudge, allowed_agents, phase)

    return f"""You are a tactical task planner for ONE phase of a web pentest.

CURRENT PHASE: {phase}
PHASE OBJECTIVE (set by strategic planner):
{phase_objective}

AGENTS AVAILABLE THIS PHASE:
{agent_lines}

{GLOBAL_RULES}
{nudge_section}
{playbook}
TASK DESCRIPTION FORMAT: Always include the current phase name at the start of
every task_description so agents can enforce their own phase lock. Example:
  "[recon] Fetch headers from http://10.0.0.1:8080/ — GET only."

OUTPUT FORMAT:
""" + tactical_parser.get_format_instructions()


# ─── User prompt ──────────────────────────────────────────────────────────────

def get_tactical_user_prompt(
    state: MasterState,
    phase_execution_history: List[Dict[str, str]],
) -> str:
    try:
        status_result = asyncio.run(run_mcp_tool("get_all_bg_task_status", {}))
        if not isinstance(status_result, dict):
            status_str = str(status_result)
        elif status_result.get("total", 0) == 0:
            status_str = "no background tasks dispatched yet"
        else:
            status_str = json.dumps(status_result, indent=2)
    except Exception as e:
        status_str = f"Error fetching — {e}"

    if not phase_execution_history:
        history_str = "None yet — first planning cycle for this phase"
    else:
        items = []
        for i, ex in enumerate(phase_execution_history, 1):
            items.append(
                f"{i}. [{ex['agent']}] {ex['task']}\n"
                f"   ➜ {ex.get('result', 'No result')}"
            )
        history_str = "\n\n".join(items)

    # Merge live cycle-level discoveries into the committed knowledge base
    # so tactical sees its own previous output within a phase, not just
    # what was committed at the last phase boundary.
    knowledge = merge_knowledge(
        state.get("knowledge", void_knowledge()),
        state.get("_extracted_knowledge", void_knowledge()),
    )

    # Surface a quick prerequisite summary so the LLM doesn't have to
    # re-derive it from the full knowledge graph on every cycle.
    phase = state.get("current_phase", "")
    prereq_summary = _build_prereq_summary(phase, knowledge)

    # Build known_cves block so vuln_analysis planner sees exactly what to test
    known_cves = knowledge.get("known_cves", []) or []
    untested_cves = [c for c in known_cves if not c.get("tested")]
    cves_block = ""
    if untested_cves:
        lines = []
        for c in untested_cves:
            tests = "; ".join(c.get("recommended_tests", [])) or "generic probe"
            lines.append(
                f"  - {c['cve_id']} ({c.get('technology','?')} {c.get('version','?')}) "
                f"severity={c.get('severity','?')} exploit={'YES' if c.get('public_exploit') else 'no'} "
                f"→ {tests}"
            )
        cves_block = (
            "\nKNOWN CVEs TO TEST (from intel_a in recon — NOT YET TESTED):\n"
            + "\n".join(lines)
            + "\nThese must be tested in vuln_analysis before moving on.\n"
        )

    return f"""ORIGINAL OBJECTIVE:
{state['query']}

PHASE OBJECTIVE:
{state['phase_objective']}

PREREQUISITE STATUS (derived from knowledge graph):
{prereq_summary}
{cves_block}
CURRENT KNOWLEDGE GRAPH:
{json.dumps(knowledge, indent=2)}

EXECUTION HISTORY FOR THIS PHASE:
{history_str}

MCP BACKGROUND TASKS STATUS:
{status_str}

Refer to the PHASE PLAYBOOK in your instructions for the correct execution
order and prerequisites. Then output the FULL batch of tasks for this cycle:
- Tasks that are truly independent go in the same batch with empty depends_on
- Tasks that must wait for others use depends_on referencing the earlier task_id
- If a prerequisite step is not yet complete, plan only up to that step
- If phase is complete: empty plan + phase_summary (no extracted_knowledge needed here)
- Do NOT repeat tasks that already succeeded in the execution history above
- Prefix every task_description with the phase name: "[{state.get('current_phase', 'unknown')}] ..."
"""


def _build_prereq_summary(phase: str, knowledge: dict) -> str:
    """
    Quick prerequisite check surfaced verbatim into the user prompt.
    Helps the LLM validate gating conditions without reading the full KG.
    """
    open_ports   = knowledge.get("open_ports",   []) or []
    web_services = knowledge.get("web_services", []) or []
    endpoints    = knowledge.get("endpoints",    []) or []
    input_points = knowledge.get("input_points", []) or []
    findings     = knowledge.get("findings",     []) or []
    known_cves   = knowledge.get("known_cves",   []) or []
    untested_cves = [c for c in known_cves if not c.get("tested")]

    http_ports = [
        p for p in open_ports
        if any(kw in str(p.get("service", "")).lower()
               for kw in ("http", "https", "web", "ssl"))
    ]

    lines = [
        f"  open_ports:      {len(open_ports)} known  "
        f"({'includes HTTP/HTTPS' if http_ports else 'no HTTP ports confirmed yet'})",
        f"  web_services:    {len(web_services)} confirmed URL(s)",
        f"  endpoints:       {len(endpoints)} discovered",
        f"  input_points:    {len(input_points)} known",
        f"  findings:        {len(findings)} recorded",
        f"  known_cves:      {len(known_cves)} total, {len(untested_cves)} untested",
    ]

    # Phase-specific gate warnings
    if phase == "recon" and not open_ports:
        lines.append("  ⚠ GATE: No ports known yet — start with nmap, not curl.")
    if phase == "recon" and open_ports and not http_ports:
        lines.append("  ⚠ GATE: No HTTP ports confirmed — do NOT run curl until nmap finds one.")
    if phase == "enumeration" and not web_services:
        lines.append("  ⚠ GATE: No web services — skip phase (return empty plan).")
    if phase == "vuln_analysis" and not input_points and not endpoints:
        lines.append("  ⚠ GATE: No input_points or endpoints — limited probing possible.")
    if phase == "vuln_analysis" and untested_cves:
        lines.append(f"  ⚠ GATE: {len(untested_cves)} known CVE(s) untested — must be addressed this phase.")
    if phase == "exploitation" and not findings:
        lines.append("  ⚠ GATE: No findings to confirm — skip phase (return empty plan).")

    return "\n".join(lines)


# ─── History slicer ───────────────────────────────────────────────────────────

def get_phase_execution_history(state: MasterState) -> List[Dict[str, str]]:
    full_history  = state.get("execution_history", [])
    phase_history = state.get("phase_history",     [])
    if not phase_history:
        return full_history
    consumed = sum(rec.get("executions_consumed", 0) for rec in phase_history)
    return full_history[consumed:]


# ─── Nodes ────────────────────────────────────────────────────────────────────

def tactical_extractor(state: MasterState) -> dict:
    """
    Node 1 of 2 in the tactical layer.

    Runs immediately after execute. Reads last_execution_results and extracts
    ONLY NEW structured findings into _extracted_knowledge. No planning.

    Keeping extraction separate from planning means:
    - The planner prompt is free of "what did we just find" noise
    - The extractor can use a cheaper/smaller model
    - The LLM isn't asked to hold two distinct cognitive tasks simultaneously
    """
    phase               = state.get("current_phase", "")
    last_results        = state.get("last_execution_results", [])
    current_knowledge   = merge_knowledge(
        state.get("knowledge", void_knowledge()),
        state.get("_extracted_knowledge", void_knowledge()),
    )

    if not last_results:
        # Nothing to extract — first cycle of the phase
        return {"last_node": "tactical_extractor"}

    results_str = "\n\n".join(
        f"[{r['agent']}] Task: {r['task']}\nResult:\n{r.get('result', '')}"
        for r in last_results
    )

    system_prompt = f"""You are a structured knowledge extractor for a penetration test.

You receive the raw output from a batch of pentesting agent tasks.
Your ONLY job: pull out NEW structured findings and add them to the knowledge graph.

RULES:
- Extract ONLY findings that are genuinely new — not already present in the
  CURRENT KNOWLEDGE GRAPH shown below.
- Do NOT re-copy existing entries. If a port is already listed, don't list it again.
- For known_cves: extract CVE entries from intel_a reports in this exact structure:
    cve_id, technology, version, severity, public_exploit (bool), github_poc (bool),
    description (one line), recommended_tests (list of strings), tested=false
- For findings: only record things that are confirmed or strongly indicated by
  the agent output — not guesses.
- If nothing new was found, return empty lists for all fields.

CURRENT KNOWLEDGE GRAPH (do NOT duplicate these):
{json.dumps(current_knowledge, indent=2)}

OUTPUT FORMAT:
""" + extractor_parser.get_format_instructions()

    user_prompt = f"""CURRENT PHASE: {phase}

EXECUTION RESULTS FROM THIS BATCH:
{results_str}

Extract only NEW findings not already in the knowledge graph above.
"""

    try:
        response = extractor_llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        parsed: TacticalExtraction = extractor_parser.parse(extract_json_block(response.content))

        accumulated = merge_knowledge(
            state.get("_extracted_knowledge", void_knowledge()),
            parsed.extracted_knowledge,
        )

        logger.info(
            f"[extractor] phase={phase} "
            f"new_ports={len(parsed.extracted_knowledge.get('open_ports',[]))} "
            f"new_services={len(parsed.extracted_knowledge.get('web_services',[]))} "
            f"new_endpoints={len(parsed.extracted_knowledge.get('endpoints',[]))} "
            f"new_findings={len(parsed.extracted_knowledge.get('findings',[]))} "
            f"new_cves={len(parsed.extracted_knowledge.get('known_cves',[]))}"
        )

        return {
            "_extracted_knowledge": accumulated,
            "last_node": "tactical_extractor",
        }

    except Exception as e:
        logger.error(f"[extractor] Failed: {e}")
        logger.info(f"Raw response: {response.content if 'response' in locals() else 'N/A'}")
        # Preserve existing _extracted_knowledge on failure — never wipe it
        return {"last_node": "tactical_extractor"}


def tactical_planner(state: MasterState) -> dict:
    """
    Node 2 of 2 in the tactical layer.

    Runs after tactical_extractor + vuln_advisor. Plans the next task batch
    only — knowledge extraction is already done by tactical_extractor.

    Key behaviours:
    - Injects phase-specific playbook (SOP with execution order + forbidden actions)
    - Injects prerequisite summary + untested CVEs so the LLM sees gate status
    - Reads VulnNudge from state and folds it into the system prompt
    - When returning an empty plan (focus/phase done), marks the current
      nudge's vuln_id as checked so the advisor never re-suggests it
    """
    phase              = state["current_phase"]
    phase_objective    = state.get("phase_objective", "")
    phase_exec_history = get_phase_execution_history(state)
    nudge              = state.get("vuln_nudge")

    messages = [
        SystemMessage(content=get_tactical_system_prompt(phase, phase_objective, nudge)),
        HumanMessage(content=get_tactical_user_prompt(state, phase_exec_history)),
    ]

    try:
        response = tactical_llm.invoke(messages)
        parsed: TacticalPlan = tactical_parser.parse(extract_json_block(response.content))

        allowed_agents = PHASE_AGENT_MAP.get(phase, [])
        validated_plan = [t.model_dump() for t in parsed.plan if t.agent in allowed_agents]
        dropped = [t.agent for t in parsed.plan if t.agent not in allowed_agents]
        if dropped:
            logger.warning(f"[tactical] Dropped out-of-scope agents for '{phase}': {dropped}")

        # When tactical signals phase/focus done (empty plan), mark the current
        # nudge's vuln_id as checked so advisor never re-suggests it.
        newly_checked: List[str] = []
        if not validated_plan and nudge and nudge.vuln_id and nudge.priority != "skip":
            newly_checked = [nudge.vuln_id]
            logger.info(f"[tactical] Marking '{nudge.vuln_id}' as checked")

        return {
            **state,
            "plan":                  validated_plan,
            "phase_iteration_count": state.get("phase_iteration_count", 0) + 1,
            "_phase_summary":        parsed.phase_summary,
            "thinking":              parsed.thinking,
            "checked_vulns":         newly_checked,
        }

    except Exception as e:
        logger.error(f"[ERROR] Tactical planner failed: {e}")
        logger.info(f"Raw response: {response.content if 'response' in locals() else 'N/A'}")
        return {
            **state,
            "plan":                  [],
            "phase_iteration_count": state.get("phase_iteration_count", 0) + 1,
            "_phase_summary":        f"Phase ended due to planner error: {e}",
            # Preserve accumulated knowledge — do NOT reset to void_knowledge()
            "_extracted_knowledge":  state.get("_extracted_knowledge", void_knowledge()),
            "thinking":              f"Error: {e}",
            "checked_vulns":         [],
        }