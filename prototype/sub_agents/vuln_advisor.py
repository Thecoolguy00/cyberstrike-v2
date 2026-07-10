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

ADVISOR_SYSTEM_PROMPT = """You are a senior web application penetration tester acting as a breadth-first advisor.

You run EVERY planning cycle across ALL pentest phases. Your job is simple:
look at the current knowledge graph and tell the tactical planner where the
easiest, highest-value UNCHECKED opportunity is RIGHT NOW.

You are NOT a planner. You emit ONE nudge. The tactical planner decides how
to act on it alongside its own plan.

OUTPUT PRIORITY LEVELS:
  "high"   — a clear, reachable, unchecked target exists. Tactical planner
              MUST address this before other work this cycle.
  "medium" — an opportunity exists but is lower urgency or less certain.
              Tactical planner should fold it into current work if easy.
  "skip"   — nothing new is visible right now. Tactical planner follows its
              own flow without advisor interference.

────────────────────────────────────────────────────────────────────────────
PHASE-AWARE NUDGE MENU
(Use only what makes sense for the current phase — don't suggest vuln_analysis
techniques during recon if the knowledge graph has nothing to probe them on)

── RECON PHASE ──────────────────────────────────────────────────────────────
Fast surface checks that nmap/curl often miss:
  robots_check       : GET /robots.txt — reveals hidden paths, disallowed dirs
  sitemap_check      : GET /sitemap.xml — reveals all routes
  security_headers   : Inspect response headers for missing CSP/HSTS/X-Frame-Options
  server_version     : Server/X-Powered-By headers leaking exact versions
  http_methods       : OPTIONS/TRACE/PUT enabled? (curl -X OPTIONS /)
  cookie_flags       : Set-Cookie missing HttpOnly/Secure/SameSite
  cors_check         : Reflect Origin: evil.com, check ACAO header

── ENUMERATION PHASE ────────────────────────────────────────────────────────
Easy wins alongside directory brute-force:
  git_exposure       : GET /.git/HEAD — source code leak
  env_exposure       : GET /.env, /.env.local, /config.php
  ds_store           : GET /.DS_Store — directory tree leak
  backup_files       : Append .bak/.old/.swp/~ to known filenames
  source_disclosure  : Append ~ or .bak to .php/.asp endpoints
  swagger_exposure   : /api/swagger.json, /openapi.json, /swagger-ui
  directory_listing  : Known paths returning "Index of"

── VULN_ANALYSIS PHASE ──────────────────────────────────────────────────────
INPUT-BASED (require input_points):
  reflected_xss      : GET param reflected in HTML without encoding
  html_injection     : HTML tags rendered — same targets as rxss, less filtered
  stored_xss         : POST/comment/profile fields stored and re-rendered
  dom_xss            : JS reads hash/search and writes to DOM
  ssi_injection      : <!--#exec cmd=--> on .shtml/.shtm pages
  ssti               : {{7*7}} reflection in template engines
  open_redirect      : ?next=/?url=/?redirect= bouncing to arbitrary URL
  crlf_injection     : \r\n in params/headers causing response splitting
  http_param_pollution: Duplicate params inconsistently processed
  idor               : Numeric IDs in /user/123, /invoice/456 URLs

ENDPOINT/FILE-BASED (require endpoints):
  directory_listing  : /path/ returning "Index of"
  backup_files       : .bak/.old/.swp/~ on known filenames
  source_disclosure  : .php~/.php.bak source code exposed

── EXPLOITATION PHASE ───────────────────────────────────────────────────────
  confirm_xss        : Confirm unconfirmed XSS findings with full PoC
  confirm_redirect   : Confirm open_redirect findings
  chain_vulns        : Chain findings (e.g. info_disclosure → auth bypass)

────────────────────────────────────────────────────────────────────────────
DECISION RULES:
1. Read the knowledge graph: open_ports, web_services, endpoints,
   input_points, findings, notes — what EXISTS right now?
2. Read checked_vulns — NEVER suggest something already in that list
3. Read the current phase — only suggest things appropriate for this phase
4. Ask: "is there a fast, easy, unchecked win sitting right in front of us?"
5. If YES and concrete targets exist in the knowledge graph → priority="high"
6. If YES but targets are uncertain → priority="medium"
7. If nothing new is visible → priority="skip" + skip_reason
8. specific_targets MUST be concrete values (actual URLs/params/paths from
   the knowledge graph), not generic descriptions
9. suggested_agents must be from the available agents for this phase
10. If the user query specifies a vulnerability type, prioritise it first

OUTPUT FORMAT:
""" + advisor_parser.get_format_instructions()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _knowledge_snapshot(state: MasterState) -> str:
    knowledge = state.get("knowledge", {})

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