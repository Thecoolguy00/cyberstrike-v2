# event_generator.py
"""
CyberStrike v3 — Event Generator.

Runs after every Extractor write (WorkerResult is merged into the master KB).
Compares the old KB snapshot to the new KB and emits typed KBEvents.

Two consumers receive these events:
  1. Dependency Orchestrator — re-evaluates PartitionDefinition matchers,
     spawns new partitions for newly unlocked work.
  2. Knowledge Enrichment Pipeline (M4) — subscribes to "tech_identified"
     events and fires async CVE / PoC lookups.

Rules
─────
- Pure pattern matching. No LLM.
- Idempotent: the same KB diff always produces the same events.
- Emits only genuinely NEW entries (present in new_kb but absent in old_kb).
- Callers must pass a consistent old_kb snapshot taken BEFORE merge_kb().
"""

from __future__ import annotations

from typing import List

from prototype.sub_agents.knowledge_partition import KBEvent, KnowledgeGraph
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))


def generate_events(
    old_kb: KnowledgeGraph,
    new_kb: KnowledgeGraph,
    source_partition: str = "",
) -> List[KBEvent]:
    """
    Diff old_kb against new_kb and return a list of KBEvents.

    Parameters
    ----------
    old_kb            : KB snapshot taken BEFORE the latest WorkerResult was merged.
    new_kb            : KB after merge_kb(old_kb, worker_result.knowledge_update).
    source_partition  : partition_id that produced the update (attached to every event).
    """
    events: List[KBEvent] = []

    # ── network.ports ─────────────────────────────────────────────────────
    old_ports = (old_kb.get("network") or {}).get("ports", {})
    new_ports = (new_kb.get("network") or {}).get("ports", {})
    for port, info in new_ports.items():
        if port not in old_ports:
            events.append(KBEvent(
                event_type="service_discovered",
                payload={
                    "port":    port,
                    "service": info.get("service", "unknown"),
                    "version": info.get("version", ""),
                    "state":   info.get("state", "open"),
                    # Canonical dependency key consumed by PartitionDefinition matchers
                    "dep_key": f"network:port:{port}",
                },
                source_partition=source_partition,
            ))
            logger.info(f"[event_generator] service_discovered port={port} service={info.get('service','?')}")

    # ── network.services (named services e.g. "apache") ───────────────────
    old_services = (old_kb.get("network") or {}).get("services", {})
    new_services = (new_kb.get("network") or {}).get("services", {})
    for svc, info in new_services.items():
        if svc not in old_services:
            events.append(KBEvent(
                event_type="named_service_discovered",
                payload={"service": svc, "info": info},
                source_partition=source_partition,
            ))

    # ── http.tech (triggers Knowledge Enrichment in M4) ───────────────────
    old_tech = (old_kb.get("http") or {}).get("tech", {})
    new_tech = (new_kb.get("http") or {}).get("tech", {})
    for tech, info in new_tech.items():
        if tech not in old_tech:
            events.append(KBEvent(
                event_type="tech_identified",
                payload={
                    "tech":    tech,
                    "version": info.get("version", "unknown") if isinstance(info, dict) else "unknown",
                    "dep_key": f"http:tech:{tech}",
                },
                source_partition=source_partition,
            ))
            logger.info(f"[event_generator] tech_identified tech={tech}")

    # ── http.endpoints ────────────────────────────────────────────────────
    old_eps = (old_kb.get("http") or {}).get("endpoints", {})
    new_eps = (new_kb.get("http") or {}).get("endpoints", {})
    for ep, info in new_eps.items():
        if ep not in old_eps:
            events.append(KBEvent(
                event_type="endpoint_discovered",
                payload={
                    "endpoint": ep,
                    "info":     info,
                    "dep_key":  f"http:endpoint:{ep}",
                },
                source_partition=source_partition,
            ))

    # ── attack_surfaces (triggers attack partitions in M2+) ───────────────
    old_surfaces = old_kb.get("attack_surfaces") or {}
    new_surfaces = new_kb.get("attack_surfaces") or {}
    for surface, info in new_surfaces.items():
        if surface not in old_surfaces:
            events.append(KBEvent(
                event_type="attack_surface_found",
                payload={
                    "surface": surface,
                    "info":    info,
                    "dep_key": f"attack_surface:{surface}",
                },
                source_partition=source_partition,
            ))
            logger.info(f"[event_generator] attack_surface_found surface={surface}")

    # ── findings ──────────────────────────────────────────────────────────
    old_findings = old_kb.get("findings") or {}
    new_findings = new_kb.get("findings") or {}
    for fid, info in new_findings.items():
        if fid not in old_findings:
            events.append(KBEvent(
                event_type="finding_recorded",
                payload={"finding_id": fid, "info": info},
                source_partition=source_partition,
            ))
            logger.info(f"[event_generator] finding_recorded id={fid}")

    return events
