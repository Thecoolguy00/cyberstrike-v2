"""Bounded Feroxbuster content stage."""

from typing import Dict, List, Tuple

from prototype.ver4.constants import DEFAULT_FEROX_MAX_RUNTIME
from prototype.ver4.parsers.ferox import parse_ferox
from prototype.ver4.schemas import Capability, ContentHit, DiscoveryBudget, DiscoveryStatus, Observation
from prototype.ver4.runtime.base import DiscoveryRuntime


async def discover_content(runtime: DiscoveryRuntime, urls: List[str], budget: DiscoveryBudget) -> Tuple[List[Observation], Dict[str, ContentHit]]:
    observations = []
    hits: Dict[str, ContentHit] = {}
    for url in urls:
        try:
            raw = await runtime.content_scan(url, min(DEFAULT_FEROX_MAX_RUNTIME, budget.max_runtime))
            parsed = parse_ferox(raw)
            for item in parsed[:budget.max_ferox_hits]:
                hit = ContentHit(**item)
                hits.setdefault(hit.url, hit)
            observations.append(Observation(capability=Capability.CONTENT, target=url, evidence={"hits": parsed[:budget.max_ferox_hits]}, raw_output=raw))
        except Exception as exc:
            observations.append(Observation(capability=Capability.CONTENT, target=url, status=DiscoveryStatus.FAILED, error=str(exc)))
    return observations, hits
