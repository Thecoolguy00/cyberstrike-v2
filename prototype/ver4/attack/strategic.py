"""Strategic step inside a scoped attack session.

Sets the attack objective (what to do within the chosen surface) from the
original query + recon evidence. Deterministic priority resolution:

1. user-requested vulnerability class (from the query)
2. untested CVEs from exploit_intelligence
3. input-based testing (XSS/SQLi) on discovered inputs
4. endpoint-based checks (backup/source disclosure)
5. configuration checks (CORS, headers, secret leaks)
"""

from typing import Dict, List, Tuple
from urllib.parse import urlparse

from prototype.ver4.schemas import DiscoveryKnowledge

VULN_HINTS: Tuple[Tuple[str, str], ...] = (
    ("xss", "XSS"),
    ("sqli", "SQL injection"),
    ("sql injection", "SQL injection"),
    ("idor", "IDOR / broken access control"),
    ("broken access", "IDOR / broken access control"),
    ("rce", "remote code execution"),
    ("command injection", "command injection"),
    ("ssrf", "SSRF"),
    ("open redirect", "open redirect"),
    ("file upload", "file upload"),
    ("upload", "file upload"),
    ("auth", "authentication/authorization"),
    ("cve", "known CVEs / exploit intel"),
    ("jwt", "JWT/token handling"),
    ("graphql", "GraphQL-specific issues"),
)


def target_tokens(target: str) -> List[str]:
    """Tokens a task description must contain to stay inside the session scope."""
    parsed = urlparse(target if "://" in target else "//" + target)
    host = parsed.hostname or ""
    if not host:
        return [target.rstrip("/").lower()]
    tokens = {target.rstrip("/").lower(), host.lower()}
    if parsed.port:
        tokens.add(f"{host}:{parsed.port}".lower())
    tokens.add(f"{parsed.scheme}://{host}".lower())
    return sorted(token for token in tokens if token)


def resolve_attack_objective(query: str, knowledge: DiscoveryKnowledge, target: str) -> str:
    lowered = (query or "").lower()
    requested = [label for keyword, label in VULN_HINTS if keyword in lowered]
    requested = list(dict.fromkeys(requested))

    untested_cves: List[str] = []
    for item in knowledge.exploit_intelligence.values():
        if item.cve and not item.tested:
            for cve_id in item.cve.split(","):
                cve_id = cve_id.strip()
                if cve_id:
                    untested_cves.append(cve_id)
    cves_str = ", ".join(dict.fromkeys(untested_cves)) or "none"

    return (
        f"Scoped attack on {target}. "
        f"FIRST priority: verify the UNVERIFIED CVEs the exploit-intel already returned "
        f"(they include CVE, severity, PoC and methodology) — confirm present/absent with "
        f"evidence using that methodology. "
        f"Unverified CVEs from intel: {cves_str}. "
        f"User-requested focus: {', '.join(requested) or 'general assessment'} (only after the CVEs above). "
        f"Surface available: {len(knowledge.endpoints)} endpoints, "
        f"{len(knowledge.inputs)} input points, {len(knowledge.technologies)} technologies, "
        f"{len(knowledge.content_hits)} content hits. "
        "Reuse the intel methodology instead of redispatching generic checks; never touch "
        "any target outside this scope."
    )