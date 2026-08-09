"""Deterministic final-report builder (no LLM)."""

from typing import List, Optional, Tuple

from prototype.ver4.schemas import DiscoveryKnowledge

SEVERITY_ORDER = ["Critical", "High", "Medium", "Low", "Info", "Unknown"]


def _severity_key(severity: str) -> int:
    try:
        return SEVERITY_ORDER.index(severity)
    except ValueError:
        return len(SEVERITY_ORDER) - 1


def _confirmed_web_targets(knowledge: DiscoveryKnowledge) -> List[str]:
    targets = []
    for observation in knowledge.http_observations:
        if observation.status is not None and observation.error is None:
            targets.append(f"{observation.final_url or observation.requested_url} (status {observation.status})")
    return sorted(set(targets))


def build_report(knowledge: DiscoveryKnowledge) -> str:
    open_ports = sorted(knowledge.ports, key=lambda value: int(value) if value.isdigit() else 99999)
    port_lines = []
    for port in open_ports:
        info = knowledge.ports[port]
        service = str(info.get("service") or "unknown")
        version = str(info.get("version") or "")
        port_lines.append(f"- {port}/tcp {service} {version}".rstrip())
    if not port_lines:
        port_lines.append("- None discovered.")

    web_targets = _confirmed_web_targets(knowledge)
    tech_lines = [
        f"- {tech.name} {tech.version or '(version unknown)'} (confidence {tech.confidence:.0%})"
        for tech in knowledge.technologies.values()
    ] or ["- None identified."]

    intel_lines = []
    for key, item in sorted(knowledge.exploit_intelligence.items()):
        tested = "tested" if item.tested else "not tested"
        intel_lines.append(
            f"- {item.technology} {item.version} -> {item.cve or 'no CVE'} "
            f"(severity {item.severity}, poc={'yes' if item.poc else 'no'}, {tested})"
        )
    if not intel_lines:
        intel_lines.append("- No exploit intelligence gathered.")

    findings = list(knowledge.findings.values())
    findings.sort(key=lambda item: _severity_key(item.severity))
    if findings:
        finding_blocks = []
        for finding in findings:
            confirmed = "Yes" if finding.confirmed else "Likely/Unconfirmed"
            finding_blocks.append(
                f"### {finding.type or 'Finding'} at {finding.location}\n"
                f"- **Severity**: {finding.severity}\n"
                f"- **Confirmed**: {confirmed}\n"
                f"- **Description**: {finding.description or 'No description.'}\n"
                f"- **Evidence**: {finding.evidence or 'See execution history / notes.'}\n"
                f"- **Source**: {finding.source or 'attack session'}"
            )
        findings_block = "\n\n".join(finding_blocks)
    else:
        findings_block = "No vulnerabilities were identified during testing."

    endpoint_lines = [f"- {url}" for url in sorted(knowledge.endpoints)] or ["- None discovered."]
    input_lines = [
        f"- {item.url} param={item.param} method={item.method} type={item.input_type or '-'}"
        for item in knowledge.inputs.values()
    ] or ["- None discovered."]
    note_lines = [f"- {note}" for note in knowledge.errors] or ["- No notes."]

    total_findings = len(findings)
    risk = "High" if total_findings else "Low"

    return f"""# Penetration Test Report

## Executive Summary
Target {knowledge.target} was assessed with deterministic discovery (L1{'/L2' if knowledge.coverage.get('recon', {}).get('network_l2', {}).get('completed') else ''}) plus scoped attack sessions.
Overall risk posture: **{risk}**. Findings recorded: **{total_findings}**.

## Target Information
- Target: {knowledge.target}
- Open Ports:
{chr(10).join(port_lines)}

## Web Services
{chr(10).join(f"- {target}" for target in web_targets) or "- None confirmed."}

## Technology Stack
{chr(10).join(tech_lines)}

## Known CVEs / Exploit Intelligence
{chr(10).join(intel_lines)}

## Findings
{findings_block}

## Discovered Endpoints
{chr(10).join(endpoint_lines)}

## Discovered Input Points
{chr(10).join(input_lines)}

## Notes & Observations
{chr(10).join(note_lines)}

## Conclusion
{("Prioritize addressing the confirmed/likely findings above, starting with the highest severity. "
   "Re-test after remediation.")
 if findings else
 ("No vulnerabilities were identified during testing. The target showed limited attack surface "
  "under the executed scope.")}
"""