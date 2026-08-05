"""Network discovery stage."""

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

from prototype.ver4.schemas import Capability, DiscoveryStatus, Observation
from prototype.ver4.parsers.nmap import parse_nmap
from prototype.ver4.runtime.base import DiscoveryRuntime


def normalize_port_list(ports: Optional[List[str]]) -> List[str]:
    """Validate and normalize optional explicit Nmap port expressions."""
    normalized = []
    for value in ports or []:
        item = str(value).strip()
        if not item or not re.fullmatch(r"\d+(?:-\d+)?", item):
            raise ValueError(f"invalid port expression: {value!r}")
        if "-" in item:
            start, end = (int(part) for part in item.split("-", 1))
            if start > end or start < 1 or end > 65535:
                raise ValueError(f"invalid port range: {value!r}")
        elif not 1 <= int(item) <= 65535:
            raise ValueError(f"invalid port: {value!r}")
        if item not in normalized:
            normalized.append(item)
    return normalized


async def discover_network(runtime: DiscoveryRuntime, target: str, ports: Optional[List[str]] = None) -> Tuple[List[Observation], Dict[str, Dict[str, Any]]]:
    observations: List[Observation] = []
    try:
        requested_ports = normalize_port_list(ports)
        merged_ports: Dict[str, Dict[str, Any]] = {}
        scan_calls = [runtime.network_scan(target)]
        if requested_ports:
            scan_calls.append(runtime.network_scan(target, requested_ports))
        scan_results = await asyncio.gather(*scan_calls, return_exceptions=True)
        for index, raw_result in enumerate(scan_results):
            scan_name = "base" if index == 0 else "optional"
            if isinstance(raw_result, Exception):
                observations.append(Observation(capability=Capability.NETWORK, target=target, status=DiscoveryStatus.FAILED, error=f"{scan_name} scan failed: {raw_result}"))
                continue
            raw = raw_result
            parsed = parse_nmap(raw)
            for item in parsed:
                port_number = str(item["port"])
                existing = merged_ports.get(port_number, {})
                merged_ports[port_number] = {**existing, **{key: value for key, value in item.items() if key != "port"}}
            observations.append(Observation(capability=Capability.NETWORK, target=target, evidence={"scan": scan_name, "ports": parsed}, raw_output=raw))
        parsed = [{"port": int(number), **details} for number, details in sorted(merged_ports.items(), key=lambda pair: int(pair[0]))]
        open_ports = [str(item["port"]) for item in parsed if item.get("state") == "open"]
        if open_ports:
            try:
                service_raw = await runtime.service_scan(target, ",".join(open_ports))
                service_items = parse_nmap(service_raw)
                for item in service_items:
                    merged_ports[str(item["port"])] = {key: value for key, value in item.items() if key != "port"}
                observations.append(Observation(capability=Capability.NETWORK, target=target, evidence={"services": service_items}, raw_output=service_raw))
            except Exception as exc:
                observations.append(Observation(capability=Capability.NETWORK, target=target, status=DiscoveryStatus.PARTIAL, error=f"service scan failed: {exc}"))
    except Exception as exc:
        observations.append(Observation(capability=Capability.NETWORK, target=target, status=DiscoveryStatus.FAILED, error=str(exc)))
        return observations, {}
    return observations, merged_ports
