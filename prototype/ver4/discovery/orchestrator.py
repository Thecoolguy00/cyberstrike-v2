"""Deterministic V4 discovery orchestration."""

import asyncio
from urllib.parse import urlparse
from typing import Dict, List, Optional

from prototype.ver4.constants import DEFAULT_MAX_RUNTIME
from prototype.ver4.discovery.content import discover_content
from prototype.ver4.discovery.html import extract_html
from prototype.ver4.discovery.http import candidate_urls, probe_http
from prototype.ver4.discovery.javascript import extract_javascript
from prototype.ver4.discovery.network import discover_network
from prototype.ver4.fingerprinting import FINGERPRINTS
from prototype.ver4.runtime.base import DiscoveryRuntime
from prototype.ver4.schemas import Capability, DiscoveryBudget, DiscoveryKnowledge, DiscoveryStatus, Endpoint, Observation, Technology


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


async def run_discovery(target: str, runtime: Optional[DiscoveryRuntime] = None, budget: Optional[DiscoveryBudget] = None, ports: Optional[List[str]] = None) -> DiscoveryKnowledge:
    target = normalize_target(target)
    if runtime is None:
        from prototype.ver4.runtime.mcpx import MCPRuntime
        runtime = MCPRuntime()
    budget = budget or DiscoveryBudget(max_runtime=DEFAULT_MAX_RUNTIME)
    knowledge = DiscoveryKnowledge(target=target)

    network_observations, discovered_ports = await discover_network(runtime, target, ports=ports)
    knowledge.observations.extend(network_observations)
    knowledge.ports.update(discovered_ports)
    knowledge.coverage.setdefault("recon", {})["network"] = {"required": True, "completed": any(item.status != DiscoveryStatus.FAILED for item in network_observations)}

    web_urls = candidate_urls(target, discovered_ports)
    http_observations, responses = await probe_http(runtime, web_urls, budget)
    knowledge.observations.extend(http_observations)
    knowledge.http_observations.extend(responses)
    confirmed_urls = sorted({item.final_url or item.requested_url for item in responses if item.status is not None and item.error is None})
    for response in responses:
        if response.status is not None:
            endpoint_url = response.final_url or response.requested_url
            knowledge.endpoints.setdefault(endpoint_url, Endpoint(url=endpoint_url, methods=[response.method], status=response.status, source="http"))
    knowledge.coverage.setdefault("recon", {})["http"] = {"required": True, "completed": bool(responses)}

    content_observations, hits = await discover_content(runtime, web_urls if confirmed_urls else [], budget)
    knowledge.observations.extend(content_observations)
    knowledge.content_hits.update(hits)
    knowledge.coverage["recon"]["content"] = {"required": bool(confirmed_urls), "completed": bool(content_observations) or not confirmed_urls}

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
    knowledge.scripts = scripts
    knowledge.coverage["recon"]["html"] = {"required": bool(selected_responses), "completed": bool(html_observations) or not selected_responses}

    js_observations, js_endpoints = await extract_javascript(runtime, scripts, budget)
    knowledge.observations.extend(js_observations)
    knowledge.endpoints.update(js_endpoints)
    knowledge.coverage["recon"]["javascript"] = {"required": bool(scripts), "completed": bool(js_observations) or not scripts}

    for response in selected_responses:
        for fingerprint in FINGERPRINTS:
            for technology in fingerprint.match(response):
                _merge_technology(knowledge, technology)
                knowledge.observations.append(Observation(capability=Capability.TECHNOLOGY, target=response.final_url or response.requested_url, evidence={"technology": technology.model_dump(mode="json")}, confidence=technology.confidence))
    knowledge.coverage["recon"]["technology"] = {"required": bool(selected_responses), "completed": bool(selected_responses)}
    for observation in knowledge.observations:
        if observation.error:
            knowledge.errors.append(f"{observation.capability.value} {observation.target}: {observation.error}")
    knowledge.errors = sorted(set(knowledge.errors))
    return knowledge


def run_discovery_sync(target: str, runtime: Optional[DiscoveryRuntime] = None, budget: Optional[DiscoveryBudget] = None, ports: Optional[List[str]] = None) -> DiscoveryKnowledge:
    return asyncio.run(run_discovery(target, runtime=runtime, budget=budget, ports=ports))
