# cyberstrike_v3.py
"""
CyberStrike v3 — Entry Point for M1 Discovery Phase.

Initializes the knowledge graph, extracts the target, and starts the Dependency Orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Dict, Any

from prototype.sub_agents.knowledge_partition import void_knowledge, KnowledgeGraph
from prototype.sub_agents.dependency_orchestrator import DependencyOrchestrator
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))


def extract_target_host(query: str) -> str:
    """
    Extract IP address or hostname from the user query.
    Falls back to '127.0.0.1' if none detected.
    """
    # Look for IPv4
    ip_match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', query)
    if ip_match:
        return ip_match.group(0)
    
    # Look for domain name
    domain_match = re.search(r'\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b', query)
    if domain_match:
        return domain_match.group(0)
        
    return "127.0.0.1"


async def run_discovery_async(query: str) -> Dict[str, Any]:
    target = extract_target_host(query)
    logger.info(f"[cyberstrike_v3] Extracted Target: {target} from query: '{query}'")

    # 1. Initialize empty namespaced knowledge graph
    knowledge = void_knowledge()
    knowledge["query_target"] = target

    # 2. Instantiate DependencyOrchestrator
    orchestrator = DependencyOrchestrator(max_concurrent=4)

    # 3. Run the orchestrator loop
    final_knowledge = await orchestrator.run(knowledge)

    # 4. Format and return results
    logger.info("=== DISCOVERY COMPLETED ===")
    logger.info(f"Open Ports: {list(final_knowledge.get('network', {}).get('ports', {}).keys())}")
    logger.info(f"Web Services: {list(final_knowledge.get('network', {}).get('services', {}).keys())}")
    logger.info(f"Discovered Endpoints: {list(final_knowledge.get('http', {}).get('endpoints', {}).keys())}")
    
    return {
        "status": "complete",
        "knowledge": final_knowledge
    }


def run_discovery(query: str) -> Dict[str, Any]:
    """Synchronous entry point."""
    return asyncio.run(run_discovery_async(query))


if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="CyberStrike v3 Discovery")
    parser.add_argument("-t", default="127.0.0.1", help="Target IP or hostname")
    parser.add_argument("-a", default="focus on info disclosure", help="Additional instructions")
    args = parser.parse_args()

    query = f"target ip: {args.t}, {args.a}"
    try:
        result = run_discovery(query)
        print(json.dumps(result, indent=2))
    except KeyboardInterrupt:
        print("\nDiscovery interrupted. Exiting cleanly.", file=sys.stderr)
        raise SystemExit(130)
