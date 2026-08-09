"""Deterministic V4 discovery orchestration.

L1 (level=1) is the base discovery (= recon). L2 (level=2) runs a background
full TCP sweep (no service detection) and applies the SAME downstream pipeline
(service scan, HTTP probe, foreground feroxbuster, HTML/JS, fingerprinting) to
ports NOT already identified by L1.
"""

import asyncio
from urllib.parse import urlparse
from typing import Dict, List, Optional

from prototype.ver4.constants import DEFAULT_MAX_RUNTIME
from prototype.ver4.discovery.content import discover_content
from prototype.ver4.discovery.html import extract_html
from prototype.ver4.discovery.http import candidate_urls, probe_http
from prototype.ver4.discovery.javascript import extract_javascript
from prototype.ver4.discovery.network import discover_network, discover_network_l2
from prototype.ver4.fingerprinting import FINGERPRINTS
from prototype.ver4.runtime.base import DiscoveryRuntime
from prototype.ver4.schemas import Capability, CoverageKeys, DiscoveryBudget, DiscoveryKnowledge, DiscoveryStatus, Endpoint, Observation, Technology


def normalize_target(target: str) -> str:
    value = target.strip()
    if not value or any(char in value for char in ("\n", "\r", "\x00", ";", "|", "&")):
        raise ValueError("target must be a single host or URL")
    parsed = urlparse(value if "://" in value else f"//{value}")
    if not parsed.hostname:
        raise ValueError("target must contain a hostname")
    return value.rstrip("/")


def _merge_technology(knowledge: DiscoveryKnowledge, item: Technology) -> None:
    existing = knowledge.technologies.get(item.name)
    if existing is None or item.confidence > existing.confidence:
        knowledge.technologies[item.name] = item
    elif existing:
        existing.evidence = sorted(set(existing.evidence + item.evidence))


def _mark_coverage(knowledge: DiscoveryKnowledge, key: str, required: bool = True, completed: bool = True) -> None:
    """OR-merge a recon coverage check so L2 never unmarks an L1 completion."""
    entry = knowledge.coverage.setdefault("recon", {}).get(key, {})
    knowledge.coverage["recon"][key] = {
        "required": bool(required or entry.get("required")),
        "completed": bool(completed or entry.get("completed")),
    }


async def run_discovery(
    target: str,
    level: int = 1,
    runtime: Optional[DiscoveryRuntime] = None,
    budget: Optional[DiscoveryBudget] = None,
    ports: Optional[List[str]] = None,
    knowledge: Optional[DiscoveryKnowledge] = None,
) -> DiscoveryKnowledge:
    target = normalize_target(target)
    if runtime is None:
        from prototype.ver4.runtime.mcpx import MCPRuntime
        runtime = MCPRuntime()
    budget = budget or DiscoveryBudget(max_runtime=DEFAULT_MAX_RUNTIME)
    prev = knowledge
    knowledge = knowledge if knowledge is not None else DiscoveryKnowledge(target=target)
    level2 = level >= 2
    known_ports = set(prev.ports) if (level2 and prev is not None) else set()

    # ── Network stage ───────────────────────────────────────────────────────
    if level2:
        network_observations, discovered_ports = await discover_network_l2(runtime, target, known_ports, budget)
        _mark_coverage(knowledge, "network", completed=bool(network_observations))
    else:
        network_observations, discovered_ports = await discover_network(runtime, target, ports=ports)
        _mark_coverage(knowledge, "network", completed=any(item.status != DiscoveryStatus.FAILED for item in network_observations))
    knowledge.observations.extend(network_observations)
    if level2:
        # Only NEW ports are merged in (never clobber L1 fingerprints); they are
        # also the only trigger for the web stage below.
        new_details = {port: details for port, details in discovered_ports.items() if port not in known_ports}
        knowledge.ports.update(new_details)
    else:
        knowledge.ports.update(discovered_ports)

    # ── Web stage (only NEW surface in the L2 case) ────────────────────────
    previous_urls = {item.final_url or item.requested_url for item in knowledge.http_observations}
    previous_roots = {value.rstrip("/") for value in previous_urls}
    if level2:
        web_urls = (
            [url for url in candidate_urls(target, new_details) if url.rstrip("/") not in previous_roots]
            if new_details else []
        )
    else:
        web_urls = candidate_urls(target, discovered_ports)
        web_urls = [url for url in web_urls if url.rstrip("/") not in previous_roots]

    http_observations, responses = await probe_http(runtime, web_urls, budget)
    knowledge.observations.extend(http_observations)
    knowledge.http_observations.extend(responses)
    confirmed_urls = sorted({item.final_url or item.requested_url for item in responses if item.status is not None and item.error is None})
    for response in responses:
        if response.status is not None:
            endpoint_url = response.final_url or response.requested_url
            knowledge.endpoints.setdefault(endpoint_url, Endpoint(url=endpoint_url, methods=[response.method], status=response.status, source="http"))
    _mark_coverage(knowledge, "http", completed=bool(http_observations))

    content_observations, hits = await discover_content(runtime, web_urls if confirmed_urls else [], budget)
    knowledge.observations.extend(content_observations)
    for url, hit in hits.items():
        knowledge.content_hits.setdefault(url, hit)
    _mark_coverage(knowledge, "content", completed=bool(content_observations) or not web_urls)

    selected_urls = confirmed_urls + sorted(hits)
    selected_responses = list(responses)
    for url in selected_urls:
        if any(item.final_url == url for item in selected_responses):
            continue
        if len(selected_responses) >= budget.max_http_requests:
            break
        try:
            raw = await runtime.http_request("GET", url, budget.max_body_size, budget.max_redirects)
            from prototype.ver4.discovery.http import _http_observation
            selected_responses.append(_http_observation("GET", url, raw))
        except Exception as exc:
            knowledge.errors.append(f"follow-up HTTP failed for {url}: {exc}")
    html_observations, html_endpoints, inputs, scripts = extract_html(selected_responses)
    knowledge.observations.extend(html_observations)
    knowledge.endpoints.update(html_endpoints)
    knowledge.inputs.update(inputs)
    prev_scripts = set(prev.scripts) if prev is not None else set()
    new_scripts = sorted(set(scripts) - prev_scripts)
    knowledge.scripts = sorted(set(knowledge.scripts) | set(scripts))
    _mark_coverage(knowledge, "html", completed=bool(html_observations) or not selected_responses)

    js_observations, js_endpoints = await extract_javascript(runtime, new_scripts, budget)
    knowledge.observations.extend(js_observations)
    knowledge.endpoints.update(js_endpoints)
    _mark_coverage(knowledge, "javascript", completed=bool(js_observations) or not new_scripts)

    for response in selected_responses:
        for fingerprint in FINGERPRINTS:
            for technology in fingerprint.match(response):
                _merge_technology(knowledge, technology)
                knowledge.observations.append(Observation(capability=Capability.TECHNOLOGY, target=response.final_url or response.requested_url, evidence={"technology": technology.model_dump(mode="json")}, confidence=technology.confidence))
    _mark_coverage(knowledge, "technology", completed=bool(selected_responses))

    if level2:
        l2_completed = any(
            obs.capability == Capability.NETWORK
            and obs.evidence.get("scan") == "l2_full"
            and obs.evidence.get("completed")
            for obs in network_observations
        )
        knowledge.coverage.setdefault("recon", {})[CoverageKeys.NETWORK_L2] = {"required": True, "completed": l2_completed}

    for observation in knowledge.observations:
        if observation.error:
            knowledge.errors.append(f"{observation.capability.value} {observation.target}: {observation.error}")
    knowledge.errors = sorted(set(knowledge.errors))
    return knowledge


def run_discovery_sync(
    target: str,
    level: int = 1,
    runtime: Optional[DiscoveryRuntime] = None,
    budget: Optional[DiscoveryBudget] = None,
    ports: Optional[List[str]] = None,
    knowledge: Optional[DiscoveryKnowledge] = None,
) -> DiscoveryKnowledge:
    return asyncio.run(run_discovery(target, level=level, runtime=runtime, budget=budget, ports=ports, knowledge=knowledge))