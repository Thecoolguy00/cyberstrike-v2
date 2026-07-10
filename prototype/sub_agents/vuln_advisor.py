# vuln_advisor.py
"""
Vulnerability Advisor Node.

Sits between the strategic planner and the tactical planner during the
vuln_analysis phase. Acts as a senior pentester who reads the current
knowledge graph and decides WHAT vulnerability class to focus on next,
and WHERE specifically to probe it.

- Runs once at the START of every vuln_analysis tactical cycle
  (i.e. after strategic hands off, and after each completed vuln focus)
- Is an LLM agent — not a static list — so it reasons over whatever
  attack surface the knowledge graph reveals
- Outputs a VulnFocus directive that tactical planner injects into its prompt
- When nothing viable remains, emits skip_reason so tactical planner
  knows to wrap the phase up rather than guess
"""

import json
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

from prototype.sub_agents.helper import extract_json_block
from app.utilities import dc_logger
from app.utilities.llm_helper import LLMHelper
from prototype.sub_agents.schemas import (
    VulnFocus,
    MasterState,
)

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))
load_dotenv()

advisor_llm    = LLMHelper.get_llm_for_service("vuln_advisor")
advisor_parser = PydanticOutputParser(pydantic_object=VulnFocus)


# ============= Prompt =============

ADVISOR_SYSTEM_PROMPT = """You are a senior web application penetration tester acting as a vulnerability advisor.

Your job: look at the current knowledge graph and decide the SINGLE most valuable
vulnerability class to focus on right now, then point the tactical planner at the
exact targets to probe.

AVAILABLE AGENTS (tactical planner uses these — your suggested_agents must come from this list):
- curl_a   — HTTP inspection, header analysis, manual request crafting
- xss_a    — XSS payload injection and detection
- python_a — Custom scripts for any test not covered by the other agents

COMPREHENSIVE VULNERABILITY MENU (use this as your reasoning palette):

=== INPUT-BASED VULNERABILITIES (require input_points in knowledge graph) ===
- reflected_xss         : User input reflected in HTML response without encoding
                          → look for GET params, search fields, error messages
- stored_xss            : Input stored and later rendered to other users
                          → look for comment fields, profile fields, POST forms
- dom_xss               : JS reads from location/document and writes to DOM unsafely
                          → look for JS-heavy pages, hash/search param usage
- html_injection        : HTML tags injected and rendered (stepping stone to XSS)
                          → same targets as reflected_xss, less strict filtering
- ssi_injection         : Server-Side Includes directives executed (<!--#exec cmd=...-->)
                          → look for .shtml/.shtm extensions, older Apache/nginx setups
- ssti                  : Template injection in Jinja2/Twig/Smarty/Freemarker
                          → look for {{7*7}} reflection, error messages mentioning templates
- open_redirect         : ?redirect=, ?url=, ?next= params that bounce user to arbitrary URL
                          → look for redirect/return/url/next/dest param names
- http_param_pollution  : Duplicate params processed inconsistently by backend vs WAF
                          → test any input point with duplicate keys
- crlf_injection        : \r\n injected into headers causing response splitting
                          → test URL params and headers like Referer/User-Agent
- cors_misconfiguration : Origin header reflected back with Access-Control-Allow-Origin: *
                          → send Origin: evil.com, check ACAO response header

=== ENDPOINT/FILE-BASED VULNERABILITIES (require endpoints in knowledge graph) ===
- directory_listing     : Server exposes file listing on directories
                          → test discovered /path/ endpoints, look for Index of
- backup_files          : .bak, .old, .swp, ~, .orig files left in web root
                          → append extensions to known filenames from ferox
- source_disclosure     : .php~, .php.bak exposing source code
                          → append ~ or .bak to discovered .php/.asp endpoints
- git_exposure          : /.git/ directory accessible, leaks source/history
                          → GET /.git/HEAD, /.git/config
- env_exposure          : /.env, /.env.local, /config.php exposed
                          → direct GET request
- ds_store_exposure     : /.DS_Store exposes directory tree on macOS-hosted servers
                          → direct GET request
- robots_disallow       : /robots.txt Disallow entries reveal hidden paths
                          → GET /robots.txt, then probe disallowed paths
- sitemap_exposure      : /sitemap.xml reveals all application routes
                          → GET /sitemap.xml
- swagger_exposure      : /api/swagger.json, /openapi.json, /swagger-ui exposed
                          → common API doc paths

=== HEADER/SERVER-BASED VULNERABILITIES (require web_services in knowledge graph) ===
- security_headers      : Missing X-Frame-Options, CSP, HSTS, X-Content-Type
                          → inspect response headers from curl
- server_version_leak   : Server/X-Powered-By headers revealing exact versions
                          → already visible in web_services.headers
- clickjacking          : No X-Frame-Options or frame-ancestors CSP
                          → check headers, try framing the page
- cookie_flags          : Sensitive cookies missing HttpOnly/Secure/SameSite flags
                          → inspect Set-Cookie headers
- http_methods          : OPTIONS/TRACE/PUT/DELETE enabled unexpectedly
                          → curl -X OPTIONS / curl -X TRACE

=== LOGIC/BEHAVIORAL VULNERABILITIES ===
- idor                  : Numeric/predictable IDs in URLs that access other users' data
                          → look for /user/123, /invoice/456 patterns in endpoints
- forced_browsing       : Unauthenticated access to authenticated endpoints
                          → probe endpoints from ferox without auth headers
- rate_limit_bypass     : No throttling on login/reset/OTP endpoints
                          → look for /login, /reset-password, /verify endpoints

DECISION RULES:
1. Read the knowledge graph carefully — open_ports, web_services, endpoints,
   input_points, findings, notes
2. Check checked_vulns — NEVER suggest a vuln_id already in this list
3. Ask: "what attack surface exists RIGHT NOW that I haven't tried yet?"
4. Pick the SINGLE most promising vuln given what's available:
   - Prefer input-based vulns if input_points exist
   - Prefer endpoint-based if only endpoints exist but no inputs yet
   - Prefer header-based if no inputs/endpoints but web_services have headers
5. Set specific_targets to CONCRETE values from the knowledge graph
   (actual URLs, param names, endpoints — not generic descriptions)
6. Set suggested_agents to only the agents that can actually probe this vuln
7. If the user query specifies a vuln type, prioritise it when preconditions are met
8. If NOTHING viable remains (all reachable vulns checked, no new attack surface),
   set skip_reason and leave all other fields empty — tactical will wrap the phase

OUTPUT FORMAT:
""" + advisor_parser.get_format_instructions()


def _knowledge_snapshot(state: MasterState) -> str:
    """Serialize flattened knowledge graph fields for the prompt."""
    snapshot = {
        "open_ports":   state.get("open_ports",   []),
        "web_services": state.get("web_services", []),
        "endpoints":    state.get("endpoints",    []),
        "input_points": state.get("input_points", []),
        "findings":     state.get("findings",     []),
        "notes":        state.get("notes",        []),
    }

    def _s(obj):
        return obj.model_dump() if hasattr(obj, "model_dump") else obj

    return json.dumps(
        {k: [_s(i) for i in v] for k, v in snapshot.items()},
        indent=2,
    )


def _advisor_user_prompt(state: MasterState) -> str:
    checked = state.get("checked_vulns", [])
    current_focus = state.get("vuln_focus")

    focus_str = ""
    if current_focus and hasattr(current_focus, "vuln_id"):
        focus_str = (
            f"\nPREVIOUS FOCUS JUST EXHAUSTED: {current_focus.vuln_id} ({current_focus.label})\n"
            f"Pick the next focus — do not repeat the previous one.\n"
        )

    return f"""ORIGINAL OBJECTIVE:
{state.get('query', '')}

CURRENT KNOWLEDGE GRAPH:
{_knowledge_snapshot(state)}

ALREADY CHECKED VULNERABILITIES (do not suggest these):
{json.dumps(checked, indent=2) if checked else '[]'}
{focus_str}
What is the SINGLE most valuable vulnerability to focus on next given
the current knowledge graph and what hasn't been tried yet?

If nothing viable remains, set skip_reason and leave other fields empty.
"""


# ============= Advisor node =============

def vuln_advisor(state: MasterState) -> dict:
    """
    Decide which vulnerability to probe next in the vuln_analysis phase.

    Returns a partial state dict with:
      - vuln_focus: VulnFocus — the directive for the tactical planner, OR
      - vuln_focus: None + skip_reason logged — signals phase exhausted
    """
    messages = [
        SystemMessage(content=ADVISOR_SYSTEM_PROMPT),
        HumanMessage(content=_advisor_user_prompt(state)),
    ]

    try:
        response = advisor_llm.invoke(messages)
        focus: VulnFocus = advisor_parser.parse(extract_json_block(response.content))

        if focus.skip_reason:
            logger.info(f"[vuln_advisor] No more viable targets: {focus.skip_reason}")
            return {
                "vuln_focus": None,
            }

        logger.info(
            f"[vuln_advisor] Focus: {focus.vuln_id} ({focus.label}) | "
            f"Targets: {focus.specific_targets}"
        )
        return {
            "vuln_focus": focus,
        }

    except Exception as e:
        logger.error(f"[ERROR] Vuln advisor failed: {e}")
        logger.info(f"Raw response: {response.content if 'response' in locals() else 'N/A'}")
        # on error, skip gracefully — don't break the graph
        return {
            "vuln_focus": None,
        }