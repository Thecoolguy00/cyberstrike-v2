"""Static JavaScript URL and API reference extraction."""

import re
from typing import Dict, List
from urllib.parse import urljoin


STRING_RE = re.compile(r"['\"]((?:https?://|/)[^'\"]{1,300})['\"]")
WS_RE = re.compile(r"(?:new\s+WebSocket|wss?://)[^'\"\s]+", re.I)


def parse_javascript(body: str, base_url: str) -> Dict[str, List[str]]:
    values = {urljoin(base_url, match) for match in STRING_RE.findall(body or "")}
    endpoints = sorted(value for value in values if any(token in value.lower() for token in ("/api", "graphql", "swagger", "openapi", ".json", ".xml")))
    urls = sorted(values)
    websockets = sorted(WS_RE.findall(body or ""))
    return {"urls": urls, "api_endpoints": endpoints, "websockets": websockets}
