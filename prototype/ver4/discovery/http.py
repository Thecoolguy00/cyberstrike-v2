"""Fixed HTTP probe stage."""

from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlparse

from prototype.ver4.constants import HTTP_PROBE_METHODS, METADATA_PATHS, WEB_PORTS
from prototype.ver4.schemas import Capability, DiscoveryStatus, DiscoveryBudget, HTTPObservation, Observation
from prototype.ver4.runtime.base import DiscoveryRuntime


def candidate_urls(target: str, ports: Dict[str, Dict[str, Any]]) -> List[str]:
    parsed = urlparse(target if "://" in target else "//" + target)
    if parsed.scheme in {"http", "https"}:
        return [target.rstrip("/")]
    host = parsed.netloc or parsed.path
    urls = []
    for port in sorted(ports, key=lambda value: int(value) if value.isdigit() else 99999):
        number = int(port) if port.isdigit() else None
        if number in WEB_PORTS:
            urls.append(f"{WEB_PORTS[number]}://{host}:{number}")
    return urls or [f"http://{host}"]


def _http_observation(method: str, url: str, response: Dict[str, Any]) -> HTTPObservation:
    headers = {str(key).lower(): str(value) for key, value in (response.get("headers") or {}).items()}
    return HTTPObservation(
        method=method,
        requested_url=url,
        final_url=str(response.get("url") or url),
        status=response.get("status"),
        headers=headers,
        cookies={str(key): str(value) for key, value in (response.get("cookies") or {}).items()},
        redirects=[str(item) for item in response.get("redirects", [])],
        content_type=str(response.get("content_type") or headers.get("content-type", "")),
        body=str(response.get("body") or ""),
        body_truncated=bool(response.get("body_truncated", False)),
        error=response.get("error"),
    )


async def probe_http(runtime: DiscoveryRuntime, urls: Iterable[str], budget: DiscoveryBudget) -> Tuple[List[Observation], List[HTTPObservation]]:
    observations: List[Observation] = []
    responses: List[HTTPObservation] = []
    count = 0
    for base_url in urls:
        paths = [""] + list(METADATA_PATHS)
        for path in paths:
            url = base_url.rstrip("/") + (f"/{path}" if path else "/")
            for method in HTTP_PROBE_METHODS:
                if count >= budget.max_http_requests:
                    return observations, responses
                count += 1
                try:
                    raw = await runtime.http_request(method, url, budget.max_body_size, budget.max_redirects)
                    item = _http_observation(method, url, raw)
                    responses.append(item)
                    observations.append(Observation(capability=Capability.HTTP, target=url, evidence={"status": item.status, "method": method, "content_type": item.content_type}, status=DiscoveryStatus.FAILED if item.error else DiscoveryStatus.SUCCESS, error=item.error))
                except Exception as exc:
                    observations.append(Observation(capability=Capability.HTTP, target=url, status=DiscoveryStatus.FAILED, error=str(exc)))
    return observations, responses
