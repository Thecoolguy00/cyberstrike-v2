# vuln_advisor.py
"""
Vulnerability Advisor — runs EVERY cycle across ALL phases.

Design intent
─────────────
The advisor is a lightweight senior-pentester layer that reads the current
knowledge graph and checked_vulns, then emits a VulnNudge telling the
tactical planner where the easiest, highest-value untried attack surface is.

It does NOT control routing (it never returns an empty plan).
It does NOT replace the tactical planner's own judgement.
It is a persistent nudge: priority="high" means "do this before other work
this cycle", priority="medium" means "keep this in mind", priority="skip"
means "nothing obvious right now, follow your own flow".

Phase gate — each phase has a strict whitelist of allowed nudge categories:
  - recon:        SERVICE_EXPLOIT_INTEL only (no testing nudges)
  - enumeration:  API_SECRET_LEAK, DIRECTORY_LISTING, SERVICE_EXPLOIT_INTEL
  - vuln_analysis / exploitation: full nudge menu active
  - reporting:    always skip

The gate is enforced in two places: the LLM system prompt (PHASE GATE block)
and _nudge_block() in tactical_planner_module.py (hard code-level drop).
Two layers because LLMs occasionally hallucinate past prompt instructions.

The vuln_id is added to checked_vulns by the tactical planner when it
returns an empty plan after working the nudge (focus exhausted), NOT when
the advisor emits it. This prevents premature marking of partially-explored
vulns.
"""

import json
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

from prototype.sub_agents.helper import extract_json_block
from app.utilities import dc_logger
from app.utilities.llm_helper import LLMHelper
from prototype.sub_agents.schemas import VulnNudge, MasterState

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))
load_dotenv()

advisor_llm    = LLMHelper.get_llm_for_service("vuln_advisor")
advisor_parser = PydanticOutputParser(pydantic_object=VulnNudge)


# ─── System prompt ────────────────────────────────────────────────────────────

ADVISOR_SYSTEM_PROMPT = """You are a senior penetration tester acting as a phase-boundary watchdog.

You run every planning cycle. Your sole job: detect if the tactical planner
is overlooking an obvious, high-value attack class given the current
knowledge graph state.

You are NOT a task planner. You do NOT prescribe how to test — only WHAT
class of attack is missing and WHERE (concrete targets from the KG).
You emit ONE nudge. The tactical planner decides how to act on it.

OUTPUT PRIORITY LEVELS:
  "high"   — a clear, reachable, unchecked class exists. Tactical planner
              MUST address this before other work this cycle.
  "medium" — an opportunity exists but lower urgency or less certain.
  "skip"   — nothing obviously missing. Tactical follows its own flow.

━━━ PHASE GATE — READ THIS FIRST ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Each phase has a STRICT whitelist of allowed nudge categories.
You MUST emit priority="skip" for any category not listed for the current phase,
regardless of how obvious or high-value the opportunity appears.
The user's query intent (e.g. "focus on xss") does NOT override phase gates.
Vulnerability testing belongs in vuln_analysis — not before it.

  recon:
    ALLOWED:   SERVICE_EXPLOIT_INTEL only
    FORBIDDEN: USER_INTENT_DRIFT, INPUT_CLASS_UNCHECKED, IDOR_UNCHECKED,
               API_SECRET_LEAK, DIRECTORY_LISTING, CLICKJACKING_UNCHECKED
    REASON:    Recon is ports + services + fingerprinting only. No testing.

  enumeration:
    ALLOWED:   API_SECRET_LEAK, DIRECTORY_LISTING, SERVICE_EXPLOIT_INTEL
    FORBIDDEN: USER_INTENT_DRIFT, INPUT_CLASS_UNCHECKED, IDOR_UNCHECKED,
               CLICKJACKING_UNCHECKED
    REASON:    Enumeration maps surface — no injection or vuln testing yet.

  vuln_analysis:
    ALLOWED:   all categories (1–7)

  exploitation:
    ALLOWED:   all categories (1–7)

  reporting:
    ALLOWED:   none — always emit priority="skip"

━━━ NUDGE CATEGORIES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. USER_INTENT_DRIFT                          [vuln_analysis, exploitation only]
   Trigger: Original query names a specific vuln type (XSS, SQLi, IDOR...),
            but no attempt of that type appears in the execution history.
   Priority: high
   Example: "User asked for XSS. No XSS attempts visible in history."

2. INPUT_CLASS_UNCHECKED                      [vuln_analysis, exploitation only]
   Trigger: knowledge.input_points is not empty AND no injection-class
            testing (XSS, SQLi, HTMLi, SSTI, open redirect) has occurred.
   Priority: high

3. IDOR_UNCHECKED                             [vuln_analysis, exploitation only]
   Trigger: Numeric IDs visible in knowledge.endpoints or input_points
            (e.g. /user/123, /invoice/456) AND no IDOR testing in history.
   Priority: high

4. API_SECRET_LEAK                            [enumeration, vuln_analysis, exploitation]
   Trigger: knowledge.web_services exists AND no page source / JS file
            secret search has occurred yet.
   Priority: medium

5. SERVICE_EXPLOIT_INTEL                      [recon, enumeration, vuln_analysis, exploitation]
   Trigger: Web services in knowledge.web_services or open ports in
            knowledge.open_ports exist, and no exploit intelligence lookup
            using intel_a has been performed yet on that service/technology.
   Priority: medium
   Example: "IIS web service identified at http://10.0.0.5:80 — run intel_a to check for public exploits."

6. DIRECTORY_LISTING                          [enumeration, vuln_analysis, exploitation]
   Trigger: knowledge.endpoints contains directory-style paths AND
            no directory listing check has occurred.
   Priority: medium

7. CLICKJACKING_UNCHECKED                     [vuln_analysis, exploitation only]
   Trigger: knowledge.web_services exists AND no X-Frame-Options or
            CSP frame-ancestors check in history.
   Priority: medium (emit only if categories 1–6 are all clear)

━━━ DECISION RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. FIRST check the PHASE GATE above — if the current phase does not allow
   any category, emit priority="skip" immediately without evaluating further.
2. Among allowed categories, check original query for a named vuln type —
   USER_INTENT_DRIFT is priority=high if unchecked AND phase allows it.
3. Evaluate remaining allowed categories in order (2–7); emit the first one
   that triggers.
4. NEVER suggest anything already in checked_vulns.
5. specific_targets MUST be concrete values from the knowledge graph
   (actual URLs, parameter names, port numbers) — NOT generic descriptions.
6. suggested_agents must be from the available agents for this phase.
7. If no allowed category triggers: priority="skip" + skip_reason.

OUTPUT FORMAT:
""" + advisor_parser.get_format_instructions()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _knowledge_snapshot(state: MasterState) -> str:
    # Merge _extracted_knowledge into knowledge so the advisor sees the
    # live state, not just what was known at the start of this phase.
    # (knowledge is only updated by merge_knowledge_node at phase end;
    #  _extracted_knowledge carries discoveries from the most recent
    #  tactical cycle before they are committed.)
    from prototype.sub_agents.schemas import merge_knowledge, void_knowledge
    knowledge = merge_knowledge(
        state.get("knowledge", void_knowledge()),
        state.get("_extracted_knowledge", void_knowledge()),
    )

    def _s(obj):
        return obj.model_dump() if hasattr(obj, "model_dump") else obj

    return json.dumps(
        {
            k: [_s(i) for i in (v if isinstance(v, list) else [])]
            for k, v in {
                "open_ports":   knowledge.get("open_ports",   []),
                "web_services": knowledge.get("web_services", []),
                "endpoints":    knowledge.get("endpoints",    []),
                "input_points": knowledge.get("input_points", []),
                "findings":     knowledge.get("findings",     []),
                "notes":        knowledge.get("notes",        []),
            }.items()
        },
        indent=2,
    )


def _build_user_prompt(state: MasterState) -> str:
    checked      = state.get("checked_vulns", [])
    current_phase = state.get("current_phase", "unknown")
    prev_nudge   = state.get("vuln_nudge")

    prev_str = ""
    if prev_nudge and prev_nudge.vuln_id:
        prev_str = (
            f"\nPREVIOUS NUDGE THIS CYCLE: {prev_nudge.vuln_id} ({prev_nudge.label}), "
            f"priority={prev_nudge.priority}. "
            f"The tactical planner has now worked on it. Pick the next nudge or skip.\n"
        )

    return f"""ORIGINAL OBJECTIVE:
{state.get('query', '')}

CURRENT PHASE: {current_phase}
PHASE OBJECTIVE: {state.get('phase_objective', '')}

CURRENT KNOWLEDGE GRAPH:
{_knowledge_snapshot(state)}

ALREADY CHECKED VULNERABILITIES (do not suggest):
{json.dumps(checked, indent=2) if checked else '[]'}
{prev_str}
Given the current phase and knowledge graph, what is the single easiest,
highest-value UNCHECKED opportunity right now?

Rules:
- Only suggest techniques appropriate for the CURRENT PHASE
- Only suggest things with concrete targets in the knowledge graph (for "high")
- Never repeat anything in checked_vulns
- If nothing clear exists: priority="skip"
"""


# ─── Node ─────────────────────────────────────────────────────────────────────

def vuln_advisor(state: MasterState) -> dict:
    """
    Emit a VulnNudge for the current cycle.
    Always returns — never blocks the graph.
    The tactical planner reads vuln_nudge and decides how to fold it in.
    """
    messages = [
        SystemMessage(content=ADVISOR_SYSTEM_PROMPT),
        HumanMessage(content=_build_user_prompt(state)),
    ]

    try:
        response = advisor_llm.invoke(messages)
        nudge: VulnNudge = advisor_parser.parse(extract_json_block(response.content))

        if nudge.priority == "skip" or not nudge.vuln_id:
            logger.info(
                f"[advisor] skip ({state.get('current_phase')}) — "
                f"{nudge.skip_reason or 'nothing actionable'}"
            )
            return {"vuln_nudge": VulnNudge(priority="skip"), "last_node": "vuln_advisor"}

        logger.info(
            f"[advisor] {nudge.priority.upper()} nudge ({state.get('current_phase')}) — "
            f"{nudge.vuln_id} | targets: {nudge.specific_targets}"
        )
        return {"vuln_nudge": nudge, "last_node": "vuln_advisor"}

    except Exception as e:
        logger.error(f"[advisor] Failed: {e}")
        logger.info(f"Raw response: {response.content if 'response' in locals() else 'N/A'}")
        return {"vuln_nudge": VulnNudge(priority="skip", skip_reason=f"advisor error: {e}"), "last_node": "vuln_advisor"}