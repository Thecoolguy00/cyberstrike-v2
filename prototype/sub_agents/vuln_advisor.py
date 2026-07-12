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

Why all phases, not just vuln_analysis?
  - During recon: nudge toward fast surface checks (robots.txt, headers)
    that are often missed when nmap dominates the planner's attention.
  - During enumeration: nudge toward backup file / .git probes alongside
    ferox directory brute-force.
  - During vuln_analysis / exploitation: full vuln menu active.

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

━━━ NUDGE CATEGORIES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. USER_INTENT_DRIFT
   Trigger: Original query names a specific vuln type (XSS, SQLi, IDOR...),
            but no attempt of that type appears in the execution history.
   Priority: high
   Example: "User asked for XSS. No XSS attempts visible in history."

2. INPUT_CLASS_UNCHECKED
   Trigger: knowledge.input_points is not empty AND no injection-class
            testing (XSS, SQLi, HTMLi, SSTI, open redirect) has occurred.
   Priority: high

3. IDOR_UNCHECKED
   Trigger: Numeric IDs visible in knowledge.endpoints or input_points
            (e.g. /user/123, /invoice/456) AND no IDOR testing in history.
   Priority: high

4. API_SECRET_LEAK
   Trigger: knowledge.web_services exists AND no page source / JS file
            secret search has occurred yet.
   Priority: medium

5. CVE_UNCHECKED  ← fires in RECON phase only
   Trigger: knowledge.open_ports contains an entry with a specific,
            non-"unknown" version string AND no CVE research for that
            service appears in knowledge.notes.
   Priority: medium
   Example: "OpenSSH 7.4 on port 22 — no CVE lookup done yet."

6. DIRECTORY_LISTING
   Trigger: knowledge.endpoints contains directory-style paths AND
            no directory listing check has occurred.
   Priority: medium

7. CLICKJACKING_UNCHECKED
   Trigger: knowledge.web_services exists AND no X-Frame-Options or
            CSP frame-ancestors check in history.
   Priority: medium (emit only if categories 1–6 are all clear)

━━━ DECISION RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Check original query for a named vuln type — always priority=high if
   unchecked (category 1 supersedes everything else)
2. Evaluate categories 2–7 in order; emit the first one that triggers
3. NEVER suggest anything already in checked_vulns
4. specific_targets MUST be concrete values from the knowledge graph
   (actual URLs, parameter names, port numbers) — NOT generic descriptions
5. suggested_agents must be from the available agents for this phase
6. If no category triggers: priority="skip" + skip_reason
7. CVE_UNCHECKED (category 5) fires ONLY during the recon phase and
   ONLY when a non-"unknown" version string is present in open_ports

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
            return {"vuln_nudge": VulnNudge(priority="skip")}

        logger.info(
            f"[advisor] {nudge.priority.upper()} nudge ({state.get('current_phase')}) — "
            f"{nudge.vuln_id} | targets: {nudge.specific_targets}"
        )
        return {"vuln_nudge": nudge}

    except Exception as e:
        logger.error(f"[advisor] Failed: {e}")
        logger.info(f"Raw response: {response.content if 'response' in locals() else 'N/A'}")
        return {"vuln_nudge": VulnNudge(priority="skip", skip_reason=f"advisor error: {e}")}