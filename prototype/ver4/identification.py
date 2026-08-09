"""Service identification node (runs between Discovery and Exploit Intelligence).

Turns raw L1/L2 discovery data (nmap labels, banners, headers, page content)
into normalized, identified services in ``knowledge.services``. This resolves
misleading nmap labels (e.g. port 3923 labelled "rtsp" but actually serving a
"Powered by copyparty" web app) so the intelligence agents research the real
server/application instead of the raw label.

Deterministic and cheap — no LLM.
"""

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from prototype.ver4.schemas import DiscoveryKnowledge

# Content markers: (name, category, content-regex, version-regex-or-None)
_CONTENT_APPS = [
    ("copyparty", "application", r"(powered\s+by\s+copyparty|/\.cpr/)", r"copyparty\s*(?:v|version[:\s]*)?(\d+\.\d+(?:\.\d+)?)"),
    ("wordpress", "application", r"(wp-content|wp-includes|wp-json)", None),
    ("laravel", "application", r"laravel_session", r"Laravel\s*v?(\d+(\.\d+)*)"),
    ("spring-boot", "application", r"/actuator|Whitelabel Error Page|spring", None),
    ("django", "application", r"csrfmiddlewaretoken|django-thumbor|X-Frame-Options.*frame", None),
]

_POWERED_RE = re.compile(r"Powered\s+by\s+([^<\n]+)")


def _url_port(url: str) -> int:
    try:
        return urlparse(url).port or (443 if url.startswith("https://") else 80)
    except ValueError:
        return 0


def _web_evidence(knowledge: DiscoveryKnowledge) -> Dict[int, Dict[str, Any]]:
    """Per symport-port web evidence: combined bodies + headers + confirmed urls."""
    evidence: Dict[int, Dict[str, Any]] = {}
    for obs in knowledge.http_observations:
        if obs.status is None or obs.error is not None or obs.status >= 400:
            continue
        port = _url_port(obs.final_url or obs.requested_url)
        if not port:
            continue
        entry = evidence.setdefault(port, {"bodies": [], "headers": {}, "urls": []})
        url = obs.final_url or obs.requested_url
        if url not in entry["urls"]:
            entry["urls"].append(url)
        if obs.body:
            entry["bodies"].append(obs.body)
        for key, value in (obs.headers or {}).items():
            entry["headers"].setdefault(key, value)
    return evidence


def _identity_from_web(port: int, web: Dict[str, Any], reported: str) -> Dict[str, Any]:
    body_text = "\n".join(web["bodies"])[:200_000]
    headers = web["headers"]
    name: str = ""
    category: str = "application"
    version: str = ""
    confidence = 0.0
    evidence: List[str] = []

    # 1) Banner/footer marker ("Powered by copyparty" etc.)
    powered = _POWERED_RE.search(body_text)
    if powered:
        candidate = powered.group(1).strip()
        if candidate and not any(ch in candidate for ch in "<>&"):
            name = candidate
            confidence = 0.85
            evidence.append(f"body: 'Powered by {candidate}'")

    # 2) Known application asset/path markers
    for app_name, app_cat, content_re, version_re in _CONTENT_APPS:
        if re.search(content_re, body_text, re.I):
            if name and name.lower() != app_name.lower():
                evidence.append(f"body: marker for {app_name} (also advertising {name})")
            else:
                name = app_name
                category = app_cat
                confidence = max(confidence, 0.9)
                evidence.append(f"body: {app_name} marker")
            if version_re:
                vm = re.search(version_re, body_text, re.I)
                if vm:
                    version = vm.group(1)
                    evidence.append(f"body: version {version}")
            break

    # 3) Header tech (server / x-powered-by) — only if no content identity yet
    if not name:
        server = headers.get("server", "") or headers.get("x-powered-by", "")
        if server:
            candidate = server.split("/")[0].strip()
            if candidate:
                name = candidate
                confidence = 0.8
                evidence.append(f"header: server/{server}")

    if not name:
        name = reported or "unknown"
        confidence = max(confidence, 0.4)

    return {
        "name": name,
        "version": version,
        "category": category,
        "confidence": round(confidence, 2),
        "reported_service": reported,
        "port": port,
        "scheme": "https" if any(obs_url.startswith("https://") for obs_url in web["urls"]) else "http",
        "urls": web["urls"],
        "evidence": evidence,
    }


def identify_services(knowledge: DiscoveryKnowledge) -> Dict[str, Dict[str, Any]]:
    """Populate ``knowledge.services[host:port]`` with normalized identities."""
    host = _target_host(knowledge)
    web_evidence = _web_evidence(knowledge)

    services: Dict[str, Dict[str, Any]] = {}
    for port_str, info in knowledge.ports.items():
        port = int(port_str) if port_str.isdigit() else None
        if port is None:
            continue
        reported = str(info.get("service") or "unknown").strip()
        version = str(info.get("version") or "").strip()
        web = web_evidence.get(port)

        if web:
            identity = _identity_from_web(port, web, reported)
            identity["location"] = f"{host}:{port}".lower()
            if not identity["version"]:
                identity["version"] = version
            services[f"{host}:{port}".lower()] = identity
        else:
            services[f"{host}:{port}".lower()] = {
                "name": reported or "unknown",
                "version": version,
                "category": "service",
                "confidence": 0.6 if reported else 0.2,
                "reported_service": reported,
                "port": port,
                "scheme": "",
                "urls": [],
                "evidence": [f"nmap label: {reported}"] if reported else [],
                "location": f"{host}:{port}".lower(),
            }

    knowledge.services = services
    return services


def _target_host(knowledge: DiscoveryKnowledge) -> str:
    target = knowledge.target or ""
    parsed = urlparse(target if "://" in target else f"//{target}")
    return parsed.hostname or target