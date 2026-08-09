"""Deterministic decision rules — skip the LLM for low-information cases."""

from typing import List, Optional
from urllib.parse import urlparse

from prototype.ver4.schemas import DecisionAction, DiscoveryKnowledge, PlannerDecision


def has_web_evidence(knowledge: DiscoveryKnowledge) -> bool:
    """Meaningful attack surface == confirmed HTTP(S) responses or discovered endpoints."""
    for observation in knowledge.http_observations:
        if observation.status is not None and observation.error is None:
            return True
    return bool(knowledge.endpoints)


def confirmed_web_targets(knowledge: DiscoveryKnowledge) -> List[str]:
    """Base URLs (scheme://host:port) that actually served HTTP(S)."""
    roots = set()
    for observation in knowledge.http_observations:
        if observation.status is None or observation.error is not None:
            continue
        url = observation.final_url or observation.requested_url
        if not url:
            continue
        parsed = urlparse(url)
        if not parsed.hostname:
            continue
        host = parsed.hostname
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        roots.add(f"{parsed.scheme}://{host}:{port}".lower())
    return sorted(roots)


def rule_decision(knowledge: DiscoveryKnowledge, full_scan_done: bool) -> Optional[PlannerDecision]:
    """
    Returns a deterministic decision, or None when the LLM should decide.

    - No meaningful web surface before L2                  → NETWORK_L2 (no LLM).
    - No meaningful web surface after L2                    → REPORT (nothing to test).
    - Meaningful web surface (HTTP/HTTPS/APIs/multi-port)   → None (LLM decides next).
    """
    if not has_web_evidence(knowledge):
        if not full_scan_done:
            return PlannerDecision(
                action=DecisionAction.NETWORK_L2,
                rationale="No confirmed web attack surface (e.g. only SSH/non-web ports). Sweeping all TCP ports deterministically.",
            )
        return PlannerDecision(
            action=DecisionAction.REPORT,
            rationale="No web attack surface even after the full L2 port sweep. Nothing to test; producing the report.",
        )
    return None