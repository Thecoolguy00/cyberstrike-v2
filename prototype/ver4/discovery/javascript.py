"""Static JavaScript normalization stage."""

from typing import Dict, List, Tuple
from urllib.parse import urlparse

from prototype.ver4.parsers.javascript import parse_javascript
from prototype.ver4.schemas import Capability, DiscoveryBudget, DiscoveryStatus, Endpoint, HTTPObservation, Observation
from prototype.ver4.runtime.base import DiscoveryRuntime


async def extract_javascript(runtime: DiscoveryRuntime, scripts: List[str], budget: DiscoveryBudget) -> Tuple[List[Observation], Dict[str, Endpoint]]:
    observations = []
    endpoints: Dict[str, Endpoint] = {}
    allowed_hosts = {urlparse(script).netloc for script in scripts}
    for script in scripts[:budget.max_js_files]:
        try:
            response = await runtime.http_request("GET", script, budget.max_body_size, budget.max_redirects)
            body = str(response.get("body") or "")
            parsed = parse_javascript(body, script)
            for endpoint in parsed["api_endpoints"] + parsed["urls"]:
                if urlparse(endpoint).netloc in allowed_hosts or not urlparse(endpoint).netloc:
                    endpoints.setdefault(endpoint, Endpoint(url=endpoint, source="javascript"))
            observations.append(Observation(capability=Capability.JAVASCRIPT, target=script, evidence=parsed, status=DiscoveryStatus.FAILED if response.get("error") else DiscoveryStatus.SUCCESS, error=response.get("error")))
        except Exception as exc:
            observations.append(Observation(capability=Capability.JAVASCRIPT, target=script, status=DiscoveryStatus.FAILED, error=str(exc)))
    return observations, endpoints
