"""Network discovery stage."""

from typing import Any, Dict, List, Tuple

from prototype.ver4.schemas import Capability, DiscoveryStatus, Observation
from prototype.ver4.parsers.nmap import parse_nmap
from prototype.ver4.runtime.base import DiscoveryRuntime


async def discover_network(runtime: DiscoveryRuntime, target: str) -> Tuple[List[Observation], Dict[str, Dict[str, Any]]]:
    observations: List[Observation] = []
    ports: Dict[str, Dict[str, Any]] = {}
    try:
        raw = await runtime.network_scan(target)
        parsed = parse_nmap(raw)
        for item in parsed:
            ports[str(item["port"])] = {key: value for key, value in item.items() if key != "port"}
        observations.append(Observation(capability=Capability.NETWORK, target=target, evidence={"ports": parsed}, raw_output=raw))
        open_ports = [str(item["port"]) for item in parsed if item.get("state") == "open"]
        if open_ports:
            try:
                service_raw = await runtime.service_scan(target, ",".join(open_ports))
                service_items = parse_nmap(service_raw)
                for item in service_items:
                    ports[str(item["port"])] = {key: value for key, value in item.items() if key != "port"}
                observations.append(Observation(capability=Capability.NETWORK, target=target, evidence={"services": service_items}, raw_output=service_raw))
            except Exception as exc:
                observations.append(Observation(capability=Capability.NETWORK, target=target, status=DiscoveryStatus.PARTIAL, error=f"service scan failed: {exc}"))
    except Exception as exc:
        observations.append(Observation(capability=Capability.NETWORK, target=target, status=DiscoveryStatus.FAILED, error=str(exc)))
    return observations, ports
