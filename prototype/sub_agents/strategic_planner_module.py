# strategic_planner_module.py
"""
Strategic planner for pentest orchestration.
Manages phase progression (recon -> enumeration -> vuln_analysis ->
exploitation -> reporting), maintains the target knowledge graph, and
decides when the overall objective is complete.

Called far less frequently than the tactical planner (once per phase
transition, not once per task), so can use a smaller/cheaper model.
"""

import json
from dotenv import load_dotenv
load_dotenv()
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

from prototype.sub_agents.helper import extract_json_block
from app.utilities import dc_logger
from app.utilities.llm_helper import LLMHelper
from prototype.sub_agents.schemas import (
    PhaseDecision,
    MasterState,
    PHASE_AGENT_MAP,
    void_knowledge,
    PHASES,
)

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))

# llm setup — strategic planner runs infrequently, so smaller model is fine
strategic_llm = LLMHelper.get_llm_for_service("strategic_planner")
strategic_parser = PydanticOutputParser(pydantic_object=PhaseDecision)


# ─── Prompts ──────────────────────────────────────────────────────────────────

def get_strategic_system_prompt() -> str:
    phase_lines = []
    for p in PHASES:
        agents = PHASE_AGENT_MAP.get(p, [])
        agent_str = ", ".join(agents) if agents else "none — synthesis only"
        phase_lines.append(f"  - {p.upper()} (agents: {agent_str})")
    phases_block = "\n".join(phase_lines)

    return f"""You are the strategic phase manager for an automated web pentesting framework.

PHASES (typically in order, but can loop back if new attack surface is discovered):
{phases_block}

PHASE DESCRIPTIONS:
  - RECON: identify open ports, services, web technology stack
  - ENUMERATION: discover endpoints, files, directories, parameters on confirmed web services
  - VULN_ANALYSIS: probe discovered input points for vulnerabilities
  - EXPLOITATION: confirm/exploit identified vulnerabilities for impact
  - REPORTING: synthesize ALL findings into a structured final pentest report (no agent execution)

PHASE TRANSITION RULES
The tactical planner signals phase completion by setting a non-empty
"phase_summary" — you will see this as the most-recently-completed phase's
summary. Use these rules to decide what happens next:

1. ADVANCE (default): When the most-recently-completed phase has a summary,
   move to the NEXT phase in order. This is the normal, expected transition.

2. LOOP BACK: When the knowledge graph reveals NEW, unexplored attack
   surface that was NOT present when the earlier phase ran (e.g. a new
   vhost, a new port, a new web service discovered during exploitation),
   loop back to the earliest phase needed to explore that surface.
   Always explain in "thinking" exactly what new surface triggered the loop.

3. SKIP: Skip phases when their prerequisites are clearly absent:
   - Skip ENUMERATION if recon found NO web services at all (only
     non-HTTP ports like SSH, FTP with no web UI). Go straight to
     VULN_ANALYSIS or EXPLOITATION for non-web services, or REPORTING
     if there is nothing to test.
   - Skip EXPLOITATION if VULN_ANALYSIS found zero potential
     vulnerabilities — go straight to REPORTING.
   - NEVER skip RECON (it is always the first phase).
   - NEVER skip REPORTING (it is always the final phase).

4. STAY: Stay in the current phase ONLY if the tactical planner's
   phase_summary explicitly says the phase needs another strategic cycle
   (extremely rare — the tactical planner handles intra-phase iteration).

YOUR JOB EACH CYCLE:
1. Review the knowledge graph and the summary of the phase that just completed
2. Apply the phase transition rules above to decide the next phase
3. Set "phase_objective" — a specific, scoped goal for the tactical planner.
   Be concrete: reference actual hosts/ports/endpoints/params from the
   knowledge graph, not generic instructions.
4. Set "current_phase" to whichever phase you've decided on next
5. Explain your reasoning in "thinking"

REPORTING PHASE — FINAL ANSWER SYNTHESIS
When you are deciding the result of a COMPLETED REPORTING phase (i.e. the
most-recently-completed phase is "reporting"), you MUST produce the
"final_answer" using the EXACT structure below. Populate every section from
the knowledge graph. Leave phase_objective empty.

FINAL ANSWER TEMPLATE:
```
# Penetration Test Report

## Executive Summary
[2-3 sentence overview: target, scope, key risk level, total findings count]

## Target Information
- Target: [IP/hostname from query]
- Open Ports: [list from knowledge.open_ports]
- Web Services: [list from knowledge.web_services]
- Technology Stack: [aggregated tech_stack from web_services]

## Findings

### [Finding 1 Title — e.g. "Reflected XSS in /search"]
- **Severity**: [Critical/High/Medium/Low/Info]
- **Location**: [URL + parameter]
- **Confirmed**: [Yes/No]
- **Description**: [what was found and how]
- **Evidence**: [relevant output/payload if available in notes]
- **Recommendation**: [specific remediation step]

### [Finding N — repeat for each finding]
...

## Discovered Endpoints
[Bullet list of all endpoints from knowledge.endpoints]

## Discovered Input Points
[Table or list of input_points with URL, param, method]

## Notes & Observations
[Bullet list from knowledge.notes — include anything not covered above]

## Conclusion
[Overall security posture assessment and priority recommendations]
```

If there are NO findings, still produce the full report structure but state
"No vulnerabilities were identified during testing" in the Findings section
and note that in the Executive Summary.

IMPORTANT:
- Do NOT generate individual agent tasks — that is the tactical planner's job
- Base decisions on the knowledge graph and phase summaries, not raw logs
- If findings list is empty after vuln_analysis/exploitation, that's a valid
  outcome — proceed to REPORTING and report "no vulnerabilities found"
- The knowledge graph is the single source of truth for all accumulated data

OUTPUT FORMAT:
""" + strategic_parser.get_format_instructions()


def get_strategic_user_prompt(state: MasterState) -> str:
    knowledge = state.get("knowledge", void_knowledge())
    phase_history = state.get("phase_history", [])
    current_phase = state.get("current_phase", "")

    if not phase_history:
        phase_history_str = "No phases completed yet — this is the start of the pentest"
    else:
        items = []
        for i, rec in enumerate(phase_history, 1):
            exec_count = rec.get("executions_consumed", 0)
            items.append(
                f"{i}. [{rec['phase']}] ({rec['iterations']} iterations, "
                f"{exec_count} executions)\n"
                f"   Summary: {rec['summary']}"
            )
        phase_history_str = "\n\n".join(items)

    last_summary = phase_history[-1]["summary"] if phase_history else "N/A"
    last_phase = phase_history[-1]["phase"] if phase_history else "N/A"

    # Build a quick stats block so the LLM can make skip decisions easily
    kg_stats = _knowledge_stats(knowledge)

    return f"""ORIGINAL OBJECTIVE:
{state['query']}

CURRENT/PREVIOUS PHASE: {current_phase or "not started"}

MOST RECENTLY COMPLETED PHASE: {last_phase}
ITS SUMMARY: {last_summary}

KNOWLEDGE GRAPH STATS (quick view for skip decisions):
{kg_stats}

FULL KNOWLEDGE GRAPH (accumulated across all phases):
{json.dumps(knowledge, indent=2)}

PHASE HISTORY:
{phase_history_str}

Based on the knowledge graph and phase history above, decide the next phase
and its objective. Apply the phase transition rules from your instructions.
If the most recently completed phase was REPORTING, produce the final_answer
using the report template instead.
"""


def _knowledge_stats(knowledge: dict) -> str:
    """One-line-per-field summary so the LLM can quickly assess skip conditions."""
    lines = []
    for key in ["open_ports", "web_services", "endpoints", "input_points", "findings", "notes"]:
        items = knowledge.get(key, [])
        count = len(items) if items else 0
        lines.append(f"  {key}: {count}")
    return "\n".join(lines)


# ─── Planning logic ──────────────────────────────────────────────────────────

def strategic_planner(state: MasterState) -> MasterState:
    """
    Decide the next phase and its objective.

    NOTE: knowledge merging is handled exclusively by merge_knowledge_node
    in master_graph.py. This function only reads the already-merged state.
    """
    knowledge = state.get("knowledge", void_knowledge())

    messages = [
        SystemMessage(content=get_strategic_system_prompt()),
        HumanMessage(content=get_strategic_user_prompt({**state, "knowledge": knowledge}))
    ]

    try:
        response = strategic_llm.invoke(messages)
        decision = strategic_parser.parse(extract_json_block(response.content))

        if decision.current_phase not in PHASES:
            logger.warning(f"[strategic] Invalid phase '{decision.current_phase}', defaulting to 'reporting'")
            decision.current_phase = "reporting"

        return {
            **state,
            "current_phase": decision.current_phase,
            "phase_objective": decision.phase_objective,
            "final_answer": decision.final_answer,
            "phase_iteration_count": 0,
            "thinking": decision.thinking,
        }

    except Exception as e:
        logger.error(f"[ERROR] Strategic planner failed: {e}")
        logger.info(f"Raw response: {response.content if 'response' in locals() else 'N/A'}")

        # Fail safe: force toward reporting to avoid infinite loops
        current = state.get("current_phase", "")
        final = ""

        if current == "reporting":
            # We were already in reporting and failed — produce a best-effort
            # final answer from whatever we have in the knowledge graph
            final = _emergency_report(state)

        return {
            **state,
            "current_phase": "reporting",
            "phase_objective": (
                "Synthesize all findings from the knowledge graph into a structured "
                "pentest report following the report template"
                if current != "reporting" else ""
            ),
            "final_answer": final,
            "phase_iteration_count": 0,
            "thinking": f"Error: {str(e)}",
        }


def _emergency_report(state: MasterState) -> str:
    """
    Best-effort final answer when the strategic planner fails during the
    reporting phase. Produces a minimal but structured report from the
    raw knowledge graph so the run doesn't end with an error string.
    """
    knowledge = state.get("knowledge", void_knowledge())
    findings = knowledge.get("findings", [])
    ports = knowledge.get("open_ports", [])
    services = knowledge.get("web_services", [])
    endpoints = knowledge.get("endpoints", [])
    notes = knowledge.get("notes", [])

    finding_lines = []
    if findings:
        for f in findings:
            confirmed = "Yes" if f.get("confirmed") else "No"
            finding_lines.append(
                f"- **{f.get('type', 'Unknown')}** at {f.get('location', 'N/A')} "
                f"(Severity: {f.get('severity', 'N/A')}, Confirmed: {confirmed})\n"
                f"  {f.get('description', '')}"
            )
    else:
        finding_lines.append("No vulnerabilities were identified during testing.")

    return f"""# Penetration Test Report (Auto-Generated — Strategic Planner Error)

## Executive Summary
This report was auto-generated because the strategic planner encountered an
error during the reporting phase. Data below is extracted directly from the
knowledge graph.

## Target Information
- Open Ports: {json.dumps(ports, indent=2)}
- Web Services: {json.dumps(services, indent=2)}

## Findings
{chr(10).join(finding_lines)}

## Discovered Endpoints
{chr(10).join(f'- {e}' for e in endpoints) or 'None discovered.'}

## Notes
{chr(10).join(f'- {n}' for n in notes) or 'None.'}
"""