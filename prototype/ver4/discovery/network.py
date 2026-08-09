"""Network discovery stage."""

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

from prototype.ver4.schemas import Capability, DiscoveryBudget, DiscoveryStatus, Observation
from prototype.ver4.parsers.nmap import parse_nmap
from prototype.ver4.runtime.base import DiscoveryRuntime


DEFAULT_POLL_INTERVAL = 2.0


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


async def discover_network_l2(
    runtime: DiscoveryRuntime,
    target: str,
    known_ports: Optional[set],
    budget: Optional[DiscoveryBudget] = None,
) -> Tuple[List[Observation], Dict[str, Dict[str, Any]]]:
    """
    L2 network discovery.

    - Starts a background full TCP sweep (1-65535) WITHOUT service detection.
    - Polls until the task completes (or the L2 runtime budget expires).
    - Service/version scan runs ONLY on ports not already identified by L1.
    """
    budget = budget or DiscoveryBudget()
    known = {str(p) for p in (known_ports or set())}
    observations: List[Observation] = []
    merged_ports: Dict[str, Dict[str, Any]] = {}
    full_raw = ""

    try:
        started = await runtime.start_long_port_scan(target, "1-65535", budget.max_l2_scan_runtime)
        task_id = str(started.get("task_id") or (started.get("output") or {}).get("task_id", ""))
        if not task_id:
            raise RuntimeError("L2 background scan did not return a task_id")

        loop = asyncio.get_event_loop()
        deadline = loop.time() + budget.max_l2_scan_runtime
        completed = False
        while loop.time() < deadline:
            try:
                meta = await runtime.get_task(task_id)
            except Exception:
                meta = {}
            if meta.get("completed"):
                completed = True
                break
            await asyncio.sleep(DEFAULT_POLL_INTERVAL)

        full_raw = await runtime.get_task_output(task_id) or ""
        parsed_full = parse_nmap(full_raw)
        open_full = [item for item in parsed_full if item.get("state") == "open"]

        for item in open_full:
            port_number = str(item["port"])
            merged_ports.setdefault(port_number, {key: value for key, value in item.items() if key != "port"})

        observations.append(Observation(
            capability=Capability.NETWORK,
            target=target,
            evidence={
                "scan": "l2_full",
                "ports": [{"port": i["port"], "state": i["state"], "service": i["service"]} for i in parsed_full],
                "known_ports_excluded": sorted(known),
                "new_ports": [i["port"] for i in open_full if str(i["port"]) not in known],
                "completed": completed,
            },
            raw_output=full_raw or None,
            status=DiscoveryStatus.FAILED if not full_raw else DiscoveryStatus.SUCCESS if completed else DiscoveryStatus.PARTIAL,
            error=None if full_raw else "full sweep returned no output (timed out or task expired)",
        ))

        # Service/version scan ONLY on ports not already identified by L1.
        new_open = [item["port"] for item in open_full if str(item["port"]) not in known]
        max_batch = budget.max_l2_service_ports_per_batch
        for batch_start in range(0, len(new_open), max_batch):
            batch = new_open[batch_start:batch_start + max_batch]
            try:
                service_raw = await runtime.service_scan(target, ",".join(str(port) for port in batch))
                service_items = parse_nmap(service_raw)
                for item in service_items:
                    merged_ports[str(item["port"])] = {key: value for key, value in item.items() if key != "port"}
                observations.append(Observation(
                    capability=Capability.NETWORK,
                    target=target,
                    evidence={"scan": "l2_services", "services": service_items, "batch": batch},
                    raw_output=service_raw,
                ))
            except Exception as exc:
                observations.append(Observation(
                    capability=Capability.NETWORK,
                    target=target,
                    status=DiscoveryStatus.PARTIAL,
                    error=f"L2 service scan failed for {batch}: {exc}",
                ))
    except Exception as exc:
        observations.append(Observation(capability=Capability.NETWORK, target=target, status=DiscoveryStatus.FAILED, error=f"L2 sweep failed: {exc}"))
        return observations, {}
    return observations, merged_ports
