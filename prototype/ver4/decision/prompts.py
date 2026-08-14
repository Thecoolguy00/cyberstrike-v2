"""Prompt construction for the Layer-2 decision planner (LLM path)."""

import json
from typing import List

from prototype.ver4.schemas import DiscoveryKnowledge, PlannerDecision


def _evidence_summary(knowledge: DiscoveryKnowledge) -> str:
    lines = []

    open_ports = sorted(knowledge.ports, key=lambda value: int(value) if value.isdigit() else 99999)
    if open_ports:
        lines.append("OPEN PORTS:")
        for port in open_ports:
            info = knowledge.ports.get(port, {})
            service = str(info.get("service") or "unknown")
            version = str(info.get("version") or "")
            lines.append(f"  {port}/tcp {service} {version}".rstrip())
    else:
        lines.append("OPEN PORTS: none")

    web_targets = []
    for observation in knowledge.http_observations:
        if observation.status is None or observation.error is not None:
            continue
        web_targets.append(f"{observation.final_url or observation.requested_url} (status {observation.status})")
    lines.append(f"WEB SERVICES: {len(web_targets)}")

    if knowledge.technologies:
        lines.append("TECHNOLOGIES:")
        for tech in knowledge.technologies.values():
            lines.append(f"  {tech.name} {tech.version or '(version unknown)'} confidence={tech.confidence:.0%}")

    if knowledge.endpoints:
        items = sorted(knowledge.endpoints)
        lines.append(f"ENDPOINTS ({len(items)}):")
        for url in items[:20]:
            lines.append(f"  {url}")
    else:
        lines.append("ENDPOINTS: none")

    api_hints = [url for url in knowledge.endpoints if any(token in url.lower() for token in ("/api", "graphql", "swagger", "openapi", "v1/", "v2/"))]
    lines.append(f"API HINTS ({len(api_hints)}): {', '.join(api_hints[:8]) or 'none'}")

    if knowledge.inputs:
        lines.append(f"INPUTS ({len(knowledge.inputs)}):")
        for item in list(knowledge.inputs.values())[:15]:
            lines.append(f"  {item.url} param={item.param} method={item.method} type={item.input_type or '-'}")

    lines.append(f"CONTENT HITS ({len(knowledge.content_hits)}): {', '.join(sorted(knowledge.content_hits)[:10]) or 'none'}")

    if knowledge.exploit_intelligence:
        lines.append("EXPLOIT INTEL:")
        for key, item in knowledge.exploit_intelligence.items():
            lines.append(f"  {key} → {item.cve or 'no CVE'} severity={item.severity} poc={'YES' if item.poc else 'no'} tested={'YES' if item.tested else 'no'}")
    else:
        lines.append("EXPLOIT INTEL: none")

    return "\n".join(lines)


def get_decision_system_prompt() -> str:
    return """You are the strategic decision planner of an automated security assessment (V4).

You decide the SINGLE next action from a compact, deterministic recon summary. The
discovery pipeline has already found open ports, web services, endpoints and input
points — you never run tools yourself.

Choose EXACTLY ONE action:

- "network_l2": request a deterministic full 1-65535 TCP sweep + service scan on newly
  found ports. Use when you believe more attack surface exists on non-standard ports
  (e.g. many non-web services, or unknown services that might wrap HTTP).
- "attack": pursue ONE already-confirmed web target now. "target" must be one of the
  WEB SERVICES confirmed by recon (scheme://host:port). Prefer the surface with the
  strongest evidence: APIs, input points, known technologies/versions, or untested CVEs.
- "report": no further meaningful attack surface. Produce the final report.

Rules:
- Only reference targets listed under WEB SERVICES.
- If the original query requests a specific vulnerability type (XSS, SQLi, IDOR, auth, ...),
  pick the target that best matches so the attack can focus on it.
- Do NOT re-attack a target that a previous decision already attacked.
- Prefer "attack" over "network_l2" when a confirmed web surface with input/endpoint
  structure already exists and the user wants results on it.
- "network_l2" and "report" must NOT set "target".
- Be decisive and brief. Assign one action with a short rationale.

OUTPUT FORMAT:
{"action": "...", "target": "...", "rationale": "..."}
"""


def get_decision_user_prompt(query: str, knowledge: DiscoveryKnowledge, decision_history: List[PlannerDecision]) -> str:
    history_str = "\n".join(
        f"  - {decision.action.value} {decision.target or ''}: {decision.rationale}"
        for decision in decision_history
    ) or "  - none yet"

    return f"""ORIGINAL QUERY:
{query}

RECON EVIDENCE (from deterministic L1/L2 discovery):
{_evidence_summary(knowledge)}

PREVIOUS DECISIONS:
{history_str}

Decide the single next action.
"""