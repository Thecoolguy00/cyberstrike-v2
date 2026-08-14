"""Exploit-intelligence node: runs right after Discovery L1/L2.

For every (service, version) / (technology, version) not yet researched, a single
intel_a task is dispatched. Results are parsed deterministically into
knowledge.exploit_intelligence so the decision planner and attack sessions can
consume them without another LLM round-trip.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from prototype.ver4.schemas import DiscoveryKnowledge, ExploitIntel

CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.I)
_ALLOWED_VERSION_WORDS = {"unknown", "na", "n/a", "-", "none", "latest"}

# Only SSH is excluded from exploit research (per requirement); the others are
# non-service placeholders, not real services. Everything else (including web apps
# and non-standard ports like rtsp/mislabelled services) is still researched.
_SKIP_PORT_SERVICES = {"ssh", "unknown", "tcp", "filtered"}

# Bare domain-looking technology names (e.g. "github.com") are fingerprint noise —
# they come from URLs in page content, not from an identified technology, and are
# never exploit-intel targets.
_DOMAIN_LIKE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", re.I)


def exploit_key(technology: str, version: Optional[str]) -> str:
    version = (version or "").strip()
    if not version or version.lower() in _ALLOWED_VERSION_WORDS:
        return technology.lower()
    return f"{technology.lower()} {version}"


def _target_host(knowledge: DiscoveryKnowledge) -> str:
    target = knowledge.target or ""
    parsed = urlparse(target if "://" in target else f"//{target}")
    return parsed.hostname or target


def _intel_candidates(knowledge: DiscoveryKnowledge) -> List[Tuple[str, Optional[str], str]]:
    """Returns (service, version, location) tuples for unresearched identified services."""
    seen = set()
    candidates: List[Tuple[str, Optional[str], str]] = []
    services = knowledge.services or _fallback_services(knowledge)

    for key, info in services.items():
        name = str(info.get("name") or "").strip()
        if not name or name.lower() in _SKIP_PORT_SERVICES or _DOMAIN_LIKE.match(name):
            continue
        version = str(info.get("version") or "").strip()
        version = None if not version or version.lower() in _ALLOWED_VERSION_WORDS else version
        dedupe_key = exploit_key(name, version)
        if dedupe_key in seen or dedupe_key in knowledge.exploit_intelligence:
            continue
        seen.add(dedupe_key)
        location = str(info.get("location") or key)
        candidates.append((name, version, location))

    return candidates


def _fallback_services(knowledge: DiscoveryKnowledge) -> Dict[str, Dict[str, Any]]:
    """Best-effort services when the identification node did not run."""
    host = _target_host(knowledge)
    services: Dict[str, Dict[str, Any]] = {}
    for port, info in knowledge.ports.items():
        service = str(info.get("service") or "unknown").strip()
        version = str(info.get("version") or "").strip() or None
        services[f"{host}:{port}".lower()] = {
            "name": service,
            "version": version,
            "location": f"{host}:{port}".lower(),
        }
    for technology in knowledge.technologies.values():
        name = technology.name.strip()
        if not name:
            continue
        services[f"tech:{name.lower()}"] = {
            "name": name,
            "version": technology.version or None,
            "location": "",
        }
    return services


def intel_task(service: str, version: Optional[str], location: str = "") -> Dict[str, Any]:
    """Task dict compatible with sub_agents/executor.py::execute_plan_parallel."""
    location_hint = f" ({location})" if location else ""
    from prototype.ver4.constants import AGENT_TASK_PHASE_PREFIX
    prefix = AGENT_TASK_PHASE_PREFIX
    if version:
        description = (
            f"{prefix} Research {service} {version}{location_hint} for known vulnerabilities "
            "and public exploits. Report exact CVE IDs, severity, PoC availability, "
            "and recommended tests."
        )
        slug = f"intel_{service}_{version}"
    else:
        description = (
            f"{prefix} Research {service}{location_hint} (unknown version) — identify the "
            "server/tech version where possible and look for known/general exploits "
            "and public PoCs."
        )
        slug = f"intel_{service}_unknown"
    task_id = re.sub(r"[^a-zA-Z0-9_]", "_", slug).lower()
    return {
        "agent": "intel_a",
        "task_description": description,
        "task_id": task_id,
        "depends_on": [],
        "coverage_keys": [],
    }


def _field(text: str, key: str) -> str:
    match = re.search(rf"^\s*{re.escape(key)}\s*:\s*(.*)$", text, re.I | re.M)
    return (match.group(1).strip().rstrip(",") if match else "")


def _parse_bool(value: str) -> bool:
    return (value or "").lower() in {"true", "yes", "y", "1"}


def _recommended_tests(text: str) -> List[str]:
    tests = []
    marker = re.search(r"recommended_tests\s*:", text, re.I)
    if not marker:
        return tests
    started = False
    for line in text[marker.end():].splitlines():
        stripped = line.strip()
        if not stripped:
            if started:
                break
            continue
        if stripped.lower().startswith(("summary", "confidence", "payloads")):
            break
        started = True
        tests.append(stripped.lstrip("- *•"))
    return [item for item in tests if item][:8]


_STOP_HEADERS = (
    "technology:", "version:", "known_vulnerabilities:", "public_exploit:",
    "github_poc:", "exploitdb:", "severity:", "recommended_tests:",
    "confidence:", "summary:",
)


def _payloads(text: str) -> List[str]:
    """Extract the verbatim payload/PoC lines from the payloads: block."""
    marker = re.search(r"^payloads\s*:", text, re.I | re.M)
    if not marker:
        return []
    payloads: List[str] = []
    current = None
    for line in text[marker.end():].splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if not stripped:
            if current is not None:
                payloads.append(current)
                current = None
            continue
        if any(low.startswith(header) for header in _STOP_HEADERS):
            break
        if stripped.startswith(("-", "*", "•")):
            if current is not None:
                payloads.append(current)
            current = stripped.lstrip("- *•").strip()
        elif current is not None:
            # continuation line of a multi-line payload (e.g. a long encoded URL)
            current = current + " " + stripped
        else:
            current = stripped
    if current is not None:
        payloads.append(current)
    return [item for item in payloads if item][:6]


def parse_intel_report(text: str) -> Optional[Dict[str, Any]]:
    """Tolerant parser for the EXPLOIT INTEL REPORT block intel_a is prompted to emit."""
    technology = _field(text, "technology") or _field(text, "name")
    if not technology:
        # Fall back to a CVE + technology-kw heuristic so genuinely useful
        # free-form output is not lost entirely.
        cves = CVE_RE.findall(text)
        if not cves:
            return None
        technology = "unknown"
    version = _field(text, "version")
    version = None if (not version or version.lower() in _ALLOWED_VERSION_WORDS) else version
    cves = list(dict.fromkeys(CVE_RE.findall(text)))
    severity = _field(text, "severity") or "Unknown"
    if severity and severity[0].isupper() is False:
        severity = severity.capitalize()
    return {
        "technology": technology,
        "version": version or "unknown",
        "cve": ", ".join(cves),
        "severity": severity,
        "poc": _parse_bool(_field(text, "public_exploit")) or _parse_bool(_field(text, "exploitdb")),
        "github_poc": _parse_bool(_field(text, "github_poc")),
        "recommended_tests": _recommended_tests(text),
        "payloads": _payloads(text),
        "summary": _field(text, "summary"),
    }


def _apply_intel_result(knowledge: DiscoveryKnowledge, text: str, location_by_key: Optional[Dict[str, str]] = None) -> bool:
    parsed = parse_intel_report(text)
    if not parsed:
        return False
    item = ExploitIntel(
        technology=parsed["technology"],
        version=parsed["version"],
        location="",
        cve=parsed["cve"],
        severity=parsed["severity"],
        poc=parsed["poc"] or parsed["github_poc"],
        description=parsed["summary"],
        recommended_tests=parsed["recommended_tests"],
        payloads=parsed["payloads"],
        tested=False,
        sources=["intel_a"],
    )
    key = exploit_key(item.technology, item.version)
    item.location = (location_by_key or {}).get(key, "")
    existing = knowledge.exploit_intelligence.get(key)
    if existing:
        item.cve = item.cve or existing.cve
        if not item.poc:
            item.poc = existing.poc
        if existing.severity in {"Critical", "High", "Medium"}:
            item.severity = item.severity if item.severity in {"Critical", "High", "Medium"} else existing.severity
        item.recommended_tests = existing.recommended_tests or item.recommended_tests
        item.payloads = existing.payloads or item.payloads
        item.sources = sorted(set(existing.sources + item.sources))
    knowledge.exploit_intelligence[key] = item
    return True


async def run_exploit_intel(knowledge: DiscoveryKnowledge, verbose: bool = True) -> int:
    """Dispatch one intel_a task per unresearched service/tech and store results.

    Returns the number of exploit-intelligence entries added/updated.
    """
    candidates = _intel_candidates(knowledge)
    if not candidates:
        return 0
    plan = [intel_task(service, version, location) for service, version, location in candidates]
    location_by_key = {exploit_key(service, version): location for service, version, location in candidates}

    # Lazy import: executor pulls in the agent graphs which connect to MCP.
    from prototype.sub_agents.executor import execute_plan_parallel

    results = await execute_plan_parallel(plan, verbose=verbose)
    added = 0
    for result in results:
        if _apply_intel_result(knowledge, result.get("result", ""), location_by_key):
            added += 1
        else:
            note = f"intel({result.get('_task_id', 'unknown')}): {result.get('result', '')[:300]}"
            if note not in knowledge.errors:
                knowledge.errors.append(note)
    knowledge.errors = sorted(set(knowledge.errors))
    return added