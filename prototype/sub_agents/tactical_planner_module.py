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
Incrementally discover the attack surface. Plan only what is executable with knowledge
you currently have. The planner will be called again after each execution batch.

State machine — follow in order, stop at first unmet condition:

STEP 1 — Port discovery (always first)
  Condition: knowledge.open_ports is empty
  Action:    nmap_a basic scan
  → Do NOT run http_a or ferox_a until ports are known.

STEP 2 — Service fingerprinting
  Condition: open_ports exist but services are not fingerprinted
  Action:    nmap_a version/banner scan on discovered ports

STEP 3 — HTTP confirmation (only if HTTP ports found)
  Condition: HTTP/HTTPS port exists (80, 443, 8080, 8443, or similar) but no web service confirmed
  Action:    http_a GET/HEAD to confirm it serves HTTP and capture headers/title

STEP 4 — Surface enumeration (only once HTTP URL is confirmed in knowledge graph)
  Condition: web service URL is confirmed
  Action:    ferox_a directory scan, http_a for JS files and param discovery
  → Do NOT start this step until step 3 is complete and a URL is in the knowledge graph.

STEP 5 — Background task check
  Condition: A background scan is running
  Action:    Check its status with the appropriate agent

STEP 6 — Phase complete
  Condition: All applicable steps are done
  Action:    Return empty plan + phase_summary

Forbidden — HARD STOPS, no exceptions
- NO injection payloads of any kind: no XSS, SQLi, template injection, command injection,
  path traversal, or parameter fuzzing. No <script>, alert(), ', ", --, ;, ../
- NO vulnerability testing of any kind.
- http_a in this phase: GET and HEAD only. No fuzzing, no payloads.
- ferox_a only after an HTTP URL is confirmed in the knowledge graph.
"""

ATTACK_ANALYSIS_PLAYBOOK = """
ATTACK ANALYSIS

Objective
Validate discovered attack surfaces (XSS, SQLi, IDOR, auth, headers, CVEs, PoCs) using passive or active techniques as appropriate.

Priority

1. User-requested vulnerability type (check original query).
2. Test known CVEs and vulnerabilities identified in the exploit intelligence list.
3. Input-based testing (XSS, SQLi, HTMLi, open redirect, IDOR).
4. Endpoint-based testing (backup files, source disclosure, directory listing).
5. Configuration checks (CORS, clickjacking, cookie flags, secret leaks).

Forbidden
- No destructive actions.
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
    "recon":           RECON_PLAYBOOK,
    "attack_analysis": ATTACK_ANALYSIS_PLAYBOOK,
    "reporting":       REPORTING_PLAYBOOK,
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
TASK DESCRIPTION FORMAT:
1. Always include the current phase name at the start of every task_description so agents can enforce their own phase lock. Example: "[recon] ..."
2. ALWAYS explicitly include the target IP, hostname, URL, or link in every single task_description, regardless of whether it is an independent or dependent task. NEVER write generic task descriptions without the specific target details (e.g. do NOT write "Scan open ports", write "Scan open ports on 10.48.152.206").

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
        # Extract native thinking
        from prototype.sub_agents.helper import extract_native_thinking
        native_thinking = extract_native_thinking(response)
        if native_thinking:
            logger.info(f"[extractor] Native Thinking: {native_thinking}")

        parsed: TacticalExtraction = extractor_parser.parse(extract_json_block(response.content))

        accumulated = merge_knowledge(
            state.get("_extracted_knowledge", void_knowledge()),
            parsed.extracted_knowledge,
        )

        # Ensure coverage dictionaries exist
        if "coverage" not in accumulated or not accumulated["coverage"]:
            accumulated["coverage"] = void_knowledge()["coverage"]
        if "attack_analysis" not in accumulated["coverage"]:
            accumulated["coverage"]["attack_analysis"] = {}

        # 1. Update coverage from successful task executions
        last_results = state.get("last_execution_results", [])
        for res in last_results:
            if res.get("status") == "SUCCESS" and res.get("coverage_keys"):
                for key in res["coverage_keys"]:
                    if phase in accumulated["coverage"] and key in accumulated["coverage"][phase]:
                        accumulated["coverage"][phase][key]["completed"] = True
                        logger.info(f"[extractor] Marked coverage completed: {phase}.{key}")

        # 1b. Prerequisite-gated promotion of recon coverage items.
        #     Items start as required=False in void_knowledge() so the reviewer
        #     cannot schedule them before their prerequisite is met.
        #     Once the prerequisite is satisfied, flip required=True so the
        #     reviewer (and planner) know this check now needs to be done.
        recon_cov = accumulated.get("coverage", {}).get("recon", {})
        ports_found = bool(accumulated.get("ports"))
        http_services_found = bool(accumulated.get("services")) or any(
            any(kw in str(v.get("service", "")).lower() for kw in ("http", "https", "web", "ssl"))
            for v in accumulated.get("ports", {}).values()
        )

        if ports_found:
            # Service fingerprinting is now executable
            if CoverageKeys.SERVICE_FINGERPRINT in recon_cov:
                recon_cov[CoverageKeys.SERVICE_FINGERPRINT]["required"] = True

        if http_services_found:
            # Directory/JS/API/param discovery are now executable
            for key in [CoverageKeys.DIR_DISCOVERY, CoverageKeys.JS_DISCOVERY,
                        CoverageKeys.API_DISCOVERY, CoverageKeys.PARAM_DISCOVERY]:
                if key in recon_cov:
                    recon_cov[key]["required"] = True

        # 2. Dynamic attack_analysis coverage generation based on discovered surface
        # Dynamic check for auth.login_testing
        endpoints_data = accumulated.get("endpoints_dict") or {}
        if isinstance(endpoints_data, dict):
            for url in endpoints_data.keys():
                if any(x in url.lower() for x in ["login", "signin", "auth", "session"]):
                    from prototype.sub_agents.schemas import CoverageKeys
                    if CoverageKeys.AUTH_LOGIN not in accumulated["coverage"]["attack_analysis"]:
                        accumulated["coverage"]["attack_analysis"][CoverageKeys.AUTH_LOGIN] = {"required": True, "completed": False}
                        logger.info(f"[extractor] Dynamically registered check: {CoverageKeys.AUTH_LOGIN}")

        # Dynamic checks for IDOR and XSS based on inputs
        inputs_data = accumulated.get("inputs") or {}
        if isinstance(inputs_data, dict):
            for val in inputs_data.values():
                if not isinstance(val, dict):
                    continue
                param = val.get("param", "").lower()
                from prototype.sub_agents.schemas import CoverageKeys
                if any(x in param for x in ["id", "uid", "user", "account", "uuid"]):
                    if CoverageKeys.IDOR_NUMERIC not in accumulated["coverage"]["attack_analysis"]:
                        accumulated["coverage"]["attack_analysis"][CoverageKeys.IDOR_NUMERIC] = {"required": True, "completed": False}
                        logger.info(f"[extractor] Dynamically registered check: {CoverageKeys.IDOR_NUMERIC}")
                if CoverageKeys.DOM_XSS not in accumulated["coverage"]["attack_analysis"]:
                    accumulated["coverage"]["attack_analysis"][CoverageKeys.DOM_XSS] = {"required": True, "completed": False}
                    logger.info(f"[extractor] Dynamically registered check: {CoverageKeys.DOM_XSS}")

        # Check for meaningful progress
        base_kb = state.get("knowledge", void_knowledge())
        
        def get_kb_size(kb):
            return (
                len(kb.get("ports", {})) +
                len(kb.get("services", {})) +
                len(kb.get("endpoints_dict", {})) +
                len(kb.get("inputs", {})) +
                len(kb.get("findings_dict", {})) +
                len(kb.get("exploit_intelligence", {}))
            )
        
        def get_completed_coverage(kb):
            count = 0
            for p in ["recon", "attack_analysis", "reporting"]:
                for check_id, check_val in kb.get("coverage", {}).get(p, {}).items():
                    if check_val.get("completed"):
                        count += 1
            return count

        base_size = get_kb_size(base_kb)
        accum_size = get_kb_size(accumulated)
        base_cov = get_completed_coverage(base_kb)
        accum_cov = get_completed_coverage(accumulated)

        metrics = state.get("metrics", {})
        stuck_cycle_count = state.get("stuck_cycle_count", 0)
        if accum_size > base_size or accum_cov > base_cov:
            logger.info(f"[extractor] Meaningful progress made! Resetting stuck cycle count. (Size: {base_size}->{accum_size}, Cov: {base_cov}->{accum_cov})")
            stuck_cycle_count = 0
        else:
            stuck_cycle_count += 1
            metrics["stuck_events"] = metrics.get("stuck_events", 0) + 1
            logger.warning(f"[extractor] No meaningful progress. Stuck cycle count: {stuck_cycle_count}/3")

        # Update coverage_completed metric
        total_completed = 0
        for p in ["recon", "attack_analysis", "reporting"]:
            for check_id, check_val in accumulated.get("coverage", {}).get(p, {}).items():
                if check_val.get("completed"):
                    total_completed += 1
        metrics["coverage_completed"] = total_completed

        # Sync legacy lists from dict changes
        from prototype.sub_agents.schemas import _sync_knowledge_legacy
        accumulated = _sync_knowledge_legacy(accumulated)

        return {
            "_extracted_knowledge": accumulated,
            "stuck_cycle_count": stuck_cycle_count,
            "last_node": "tactical_extractor",
            "metrics": metrics,
        }

    except Exception as e:
        logger.error(f"[extractor] Failed: {e}")
        logger.info(f"Raw response: {response.content if 'response' in locals() else 'N/A'}")
        return {
            "last_node": "tactical_extractor",
            "stuck_cycle_count": state.get("stuck_cycle_count", 0)
        }


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
        # Extract native thinking
        from prototype.sub_agents.helper import extract_native_thinking
        native_thinking = extract_native_thinking(response)

        # Fallback to checking if model still generated thinking inside JSON block
        if not native_thinking:
            try:
                json_data = json.loads(extract_json_block(response.content))
                native_thinking = json_data.get("thinking", "")
            except Exception:
                pass

        parsed: TacticalPlan = tactical_parser.parse(extract_json_block(response.content))

        allowed_agents = PHASE_AGENT_MAP.get(phase, [])
        validated_plan = [t.model_dump() for t in parsed.plan if t.agent in allowed_agents]
        
        # Injects live cycle-level discoveries into the committed knowledge base
        knowledge = merge_knowledge(
            state.get("knowledge", void_knowledge()),
            state.get("_extracted_knowledge", void_knowledge()),
        )

        # Injected Rule 1: Exploit Intel scheduling & duplicate checks
        bg_tasks = knowledge.get("background_tasks", {})
        running_or_done_tasks = set(bg_tasks.keys())
        for ex in state.get("execution_history", []):
            if ex.get("task"):
                running_or_done_tasks.add(ex["task"])

        injected_tasks = []
        for s_name, val in knowledge.get("services", {}).items():
            version = val.get("version", "unknown")
            if version != "unknown":
                tech_ver = f"{s_name} {version}"
                
                # Check duplicate lookups
                intel_task_desc = f"Research {s_name} {version} for known vulnerabilities"
                if tech_ver not in knowledge.get("exploit_intelligence", {}) and intel_task_desc not in running_or_done_tasks:
                    logger.info(f"[tactical] Auto-scheduling exploit intel lookup for: {tech_ver}")
                    injected_tasks.append({
                        "agent": "intel_a",
                        "task_description": f"[{phase}] {intel_task_desc}",
                        "task_id": f"intel_auto_{s_name}_{version}".replace(".", "_"),
                        "depends_on": [],
                        "coverage_keys": []
                    })
                    running_or_done_tasks.add(intel_task_desc)

        # Injected Rule 2: CVE validation tasks & duplicate checks
        for s_name, intel in knowledge.get("exploit_intelligence", {}).items():
            cve_id = intel.get("cve")
            if cve_id:
                # Find if a verification task has already been scheduled or run
                cve_task_desc = f"Verify vulnerability {cve_id} on service {s_name}"
                if cve_task_desc not in running_or_done_tasks:
                    logger.info(f"[tactical] Auto-scheduling CVE verification for: {cve_id}")
                    # Use appropriate test agent or python/http validation agent
                    target_agent = "python_a" if phase == "attack_analysis" else "http_a"
                    injected_tasks.append({
                        "agent": target_agent,
                        "task_description": f"[{phase}] {cve_task_desc}",
                        "task_id": f"cve_verify_{cve_id.replace('-', '_')}",
                        "depends_on": [],
                        "coverage_keys": []
                    })
                    running_or_done_tasks.add(cve_task_desc)

        # Prepend auto-scheduled tasks
        validated_plan = injected_tasks + validated_plan

        # De-duplicate any broad task description duplicates inside the plan
        deduped_plan = []
        seen_descs = set()
        duplicates_removed_count = 0
        for t in validated_plan:
            desc = t["task_description"]
            if desc not in seen_descs and desc not in running_or_done_tasks:
                deduped_plan.append(t)
                seen_descs.add(desc)
            else:
                logger.info(f"[tactical] Dropped duplicate or already-running task: {desc}")
                duplicates_removed_count += 1

        # Track metrics
        metrics = state.get("metrics", {})
        metrics["cycles"] = metrics.get("cycles", 0) + 1
        intel_count = sum(1 for t in deduped_plan if t.get("agent") == "intel_a")
        metrics["intel_tasks"] = metrics.get("intel_tasks", 0) + intel_count
        metrics["duplicate_tasks_removed"] = metrics.get("duplicate_tasks_removed", 0) + duplicates_removed_count

        dropped = [t.agent for t in parsed.plan if t.agent not in allowed_agents]
        if dropped:
            logger.warning(f"[tactical] Dropped out-of-scope agents for '{phase}': {dropped}")

        # When tactical signals phase/focus done (empty plan), mark the current
        # nudge's vuln_id as checked so advisor never re-suggests it.
        newly_checked: List[str] = []
        if not deduped_plan and nudge and nudge.vuln_id and nudge.priority != "skip":
            newly_checked = [nudge.vuln_id]
            logger.info(f"[tactical] Marking '{nudge.vuln_id}' as checked")

        return {
            **state,
            "plan":                  deduped_plan,
            "phase_iteration_count": state.get("phase_iteration_count", 0) + 1,
            "_phase_summary":        parsed.phase_summary,
            "thinking":              native_thinking,
            "checked_vulns":         newly_checked,
            "metrics":               metrics,
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