# partition_definitions.py
"""
CyberStrike v3 — Partition Definitions Registry.

Defines the templates and prerequisite matches for Discovery domains.
"""

from typing import List, Dict, Any
from prototype.sub_agents.knowledge_partition import PartitionDefinition, KnowledgeGraph


def network_matcher(kb: KnowledgeGraph) -> List[Dict[str, str]]:
    """
    Find target for network scanning.
    Runs exactly once per target host if network.ports is empty.
    """
    ports = kb.get("network", {}).get("ports", {})
    if ports:
        return []
    
    target = kb.get("query_target")
    if not target:
        return []
    
    return [{"target": target}]


def http_matcher(kb: KnowledgeGraph) -> List[Dict[str, str]]:
    """
    Find HTTP targets from open ports in the KB.
    Creates one HTTP partition per discovered HTTP/HTTPS service.
    """
    targets = []
    ports = kb.get("network", {}).get("ports", {})
    
    # We fallback to target IP/hostname from the query
    host = kb.get("query_target", "")
    if not host:
        return []

    for port_str, info in ports.items():
        service = str(info.get("service", "")).lower()
        port_num = int(port_str) if port_str.isdigit() else 0
        
        is_http = (
            any(kw in service for kw in ["http", "https", "web", "ssl"]) or
            port_num in [80, 443, 8000, 8080, 8443, 8888]
        )
        if is_http:
            # build URL target
            scheme = "https" if (port_num == 443 or "https" in service or "ssl" in service) else "http"
            url = f"{scheme}://{host}:{port_num}"
            targets.append({
                "target": url,
                "port": port_str,
                "service": service
            })
            
    return targets


# Registry of all discovery partition templates
PARTITION_DEFINITIONS = [
    PartitionDefinition(
        domain="network",
        goal_template="Discover alive hosts, open ports, and service versions on target: {target}",
        produces=["network:ports", "network:services"],
        prerequisite_matcher=network_matcher,
    ),
    PartitionDefinition(
        domain="http",
        goal_template="Map HTTP surface on target: {target} (fingerprint, status codes, headers, robots, directories, JS, parameters)",
        produces=["http:endpoints", "http:forms", "http:tech", "http:headers"],
        prerequisite_matcher=http_matcher,
    )
]
