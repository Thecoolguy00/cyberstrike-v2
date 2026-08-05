# knowledge_partition.py
"""
CyberStrike v3 — Foundation Layer.

All units of work, data contracts, and knowledge graph types live here.
Nothing else in v3 should be built before this file is stable.

Design notes
────────────
KnowledgePartition   — the unit of work passed to the Dependency Orchestrator
                       and then to a Domain Worker.
PartitionDefinition  — a registered template. The Orchestrator instantiates
                       instances whenever the prerequisite_matcher finds a
                       matching target in the current KB.
KBEvent              — a typed event emitted by the Event Generator after
                       every Extractor write. Two consumers: the Orchestrator
                       (re-evaluates matchers) and the Enrichment Pipeline.
WorkerResult         — the output contract of every Domain Worker. The
                       Orchestrator merges knowledge_update into the master
                       KB and forwards events to the Event Generator.
KnowledgeGraph       — protocol-namespaced dict. Workers own their namespace.
                       No two workers write to the same key.

Dependency key convention (used in prerequisites / produces)
────────────────────────────────────────────────────────────
  Format:  "namespace:key:value"
  Examples:
    network:port:80            # port 80 is open
    network:port:443
    http:endpoint:/upload      # /upload was discovered
    http:tech:apache           # Apache fingerprinted
    attack_surface:xss         # XSS surface detected
    attack_surface:upload      # upload endpoint surface detected
    intel:apache               # intel lookup done for Apache
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypedDict


# ─── Partition status ─────────────────────────────────────────────────────────

class PartitionStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    COMPLETE = "complete"
    FAILED   = "failed"


# ─── Knowledge Graph ──────────────────────────────────────────────────────────

class KnowledgeGraph(TypedDict, total=False):
    """
    Protocol-namespaced knowledge graph.

    Each namespace is owned by one class of Domain Worker.
    Workers must not write outside their own namespace.
    The Orchestrator merges namespaces with dict.update() — no clobbering
    as long as workers respect ownership.
    """
    # ── Discovery namespaces ──────────────────────────────────────────────
    network: Dict[str, Any]
    # {
    #   "ports":    {"80": {"service": "http", "version": "Apache/2.4.49", "state": "open"}, ...},
    #   "services": {"apache": {"port": 80, "version": "2.4.49"}},
    #   "os":       {"guess": "Linux 5.x", "confidence": 85},
    # }

    http: Dict[str, Any]
    # {
    #   "endpoints":  {"/admin": {"methods": ["GET"], "status": 200}, ...},
    #   "forms":      {"/login": [{"action": "/auth", "inputs": ["user","pass"]}]},
    #   "headers":    {"Server": "Apache/2.4.49", "X-Frame-Options": "SAMEORIGIN"},
    #   "tech":       {"apache": {"version": "2.4.49"}, "wordpress": {"version": "6.1"}},
    #   "js_files":   ["/static/app.js"],
    #   "robots":     ["Disallow: /admin"],
    # }

    ssh: Dict[str, Any]
    # {
    #   "banner":       "OpenSSH 9.8",
    #   "algos":        ["ecdh-sha2-nistp256", ...],
    #   "auth_methods": ["publickey", "password"],
    # }

    smb: Dict[str, Any]
    # {
    #   "version": "SMBv2",
    #   "shares":  {"SYSVOL": {"access": "read"}, "ADMIN$": {"access": "none"}},
    # }

    ftp: Dict[str, Any]
    # {
    #   "banner":     "vsftpd 3.0.3",
    #   "anon_login": False,
    # }

    # ── Intelligence namespace ────────────────────────────────────────────
    intel: Dict[str, Any]
    # {
    #   "apache": {
    #     "cves": ["CVE-2021-41773", ...],
    #     "pocs": ["https://github.com/..."],
    #     "severity": "Critical",
    #   }
    # }

    # ── Attack surface + findings ─────────────────────────────────────────
    attack_surfaces: Dict[str, Any]
    # {
    #   "xss":    {"endpoints": ["/search?q="], "confirmed": False},
    #   "upload": {"endpoints": ["/admin/upload"], "confirmed": False},
    # }

    findings: Dict[str, Any]
    # {
    #   "xss_search_q": {"type": "XSS", "location": "/search?q=", "confirmed": True, "severity": "High"},
    # }

    # ── Operational namespaces (preserved from v2) ────────────────────────
    coverage:         Dict[str, Any]
    background_tasks: Dict[str, Any]

    # ── Campaign metadata ─────────────────────────────────────────────────
    query_target: str   # the original target string supplied to run_discovery()


def void_knowledge() -> KnowledgeGraph:
    """Return a fresh, empty KnowledgeGraph."""
    from prototype.sub_agents.schemas import void_knowledge as void_legacy
    kb = void_legacy()
    kb.update({
        "network": {},
        "http": {},
        "ssh": {},
        "smb": {},
        "ftp": {},
        "intel": {},
        "attack_surfaces": {},
        "findings": {},
        "query_target": "",
    })
    return kb


def merge_kb(base: KnowledgeGraph, update: KnowledgeGraph) -> KnowledgeGraph:
    """
    Deep-merge *update* into *base*.
    Uses schemas.merge_knowledge to merge legacy structures and then
    syncs/maps them to the new namespaced v3 structure.
    """
    from prototype.sub_agents.schemas import merge_knowledge
    
    # 1. Merge legacy/flat structures
    merged_legacy = merge_knowledge(base, update)
    
    # 2. Sync to namespaced v3 structures
    merged_legacy["network"] = merged_legacy.get("network") or {}
    merged_legacy["network"]["ports"] = merged_legacy.get("ports", {})
    merged_legacy["network"]["services"] = merged_legacy.get("services", {})
    
    merged_legacy["http"] = merged_legacy.get("http") or {}
    merged_legacy["http"]["endpoints"] = merged_legacy.get("endpoints_dict", {})
    merged_legacy["http"]["inputs"] = merged_legacy.get("inputs", {})
    
    merged_legacy["findings"] = merged_legacy.get("findings_dict", {})
    merged_legacy["intel"] = merged_legacy.get("exploit_intelligence", {})
    
    if update.get("query_target"):
        merged_legacy["query_target"] = update["query_target"]
        
    return merged_legacy


# ─── Typed events ─────────────────────────────────────────────────────────────

@dataclass
class KBEvent:
    """
    A typed event emitted by the Event Generator.

    event_type examples
    ───────────────────
    "service_discovered"   — new entry in network.ports or network.services
    "tech_identified"      — new entry in http.tech (triggers enrichment)
    "endpoint_discovered"  — new entry in http.endpoints
    "attack_surface_found" — new entry in attack_surfaces (triggers attack partition)
    "finding_recorded"     — confirmed or unconfirmed finding in findings
    """
    event_type: str
    payload:    Dict[str, Any]
    source_partition: str = ""   # partition_id that produced this event


# ─── Worker result ────────────────────────────────────────────────────────────

@dataclass
class WorkerResult:
    """
    Output contract of every Domain Worker.

    The Orchestrator:
    1. Merges knowledge_update into the master KG via merge_kb().
    2. Forwards events to the Event Generator.
    3. Marks the partition as COMPLETE or FAILED.
    """
    partition_id:     str
    knowledge_update: KnowledgeGraph
    events:           List[KBEvent] = field(default_factory=list)
    status:           str = "complete"   # "complete" | "failed" | "partial"
    error:            str = ""


# ─── Partition ────────────────────────────────────────────────────────────────

@dataclass
class KnowledgePartition:
    """
    The unit of work.

    Created either by the Dependency Orchestrator (from a PartitionDefinition
    when prerequisites are satisfied) or by the deterministic translator that
    converts an AttackHypothesis into a runnable partition.

    partition_id must be globally unique for a given target + domain combo
    so the Orchestrator can deduplicate.
    """
    domain:        str              # "network" | "http" | "ssh" | "xss" | "upload" | ...
    target:        str              # concrete IP, URL, or endpoint
    goal:          str              # passed verbatim into the Partition Planner prompt
    prerequisites: List[str]        # dependency key strings — all must exist in KB
    produces:      List[str]        # dependency key strings this partition will write
    partition_id:  str = field(default_factory=lambda: str(uuid.uuid4()))
    status:        PartitionStatus = PartitionStatus.PENDING
    metadata:      Dict[str, Any]  = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "partition_id":  self.partition_id,
            "domain":        self.domain,
            "target":        self.target,
            "goal":          self.goal,
            "prerequisites": self.prerequisites,
            "produces":      self.produces,
            "status":        self.status.value,
            "metadata":      self.metadata,
        }


# ─── Partition definition (template) ─────────────────────────────────────────

@dataclass
class PartitionDefinition:
    """
    A registered partition template.

    The Dependency Orchestrator holds a registry of PartitionDefinitions.
    After every KB update it asks each definition:
        "Given the current KB, what new KnowledgePartition instances should exist?"

    prerequisite_matcher
    ────────────────────
    A callable that receives the current KnowledgeGraph and returns a list of
    (target, metadata) tuples. Each tuple becomes one KnowledgePartition
    instance. Return an empty list if no new instances should be created.

    The Orchestrator deduplicates by checking whether a partition with the
    same (domain, target) already exists in its registry.
    """
    domain:       str
    goal_template: str          # f-string-safe; receives target=<target>
    produces:     List[str]
    prerequisite_matcher: Callable[[KnowledgeGraph], List[Dict[str, str]]]
    # each dict: {"target": "...", **optional_metadata}

    def instantiate(self, target: str, metadata: Optional[Dict[str, Any]] = None) -> KnowledgePartition:
        """Create a KnowledgePartition from this definition for the given target."""
        goal = self.goal_template.format(target=target)
        # Prerequisites are inferred from the matcher — the orchestrator
        # already confirmed they're satisfied before calling instantiate.
        return KnowledgePartition(
            domain        = self.domain,
            target        = target,
            goal          = goal,
            prerequisites = [],   # satisfied by definition at instantiation time
            produces      = self.produces,
            metadata      = metadata or {},
            partition_id  = f"{self.domain}_{target.replace('://', '_').replace('/', '_').replace(':', '_')}",
        )


# ─── Attack Hypothesis (Validation phase — M3) ───────────────────────────────

@dataclass
class AttackHypothesis:
    """
    Output of the Attack Planner (validation phase only).

    A deterministic translator converts one AttackHypothesis into one
    KnowledgePartition. The Orchestrator never sees the hypothesis directly —
    only the resulting partition.

    Deferred to M3. Defined here so the schema is stable from day one.
    """
    hypothesis_id:       str
    domain:              str
    target:              str
    goal:                str
    rationale:           str
    confidence:          float        # 0.0 – 1.0
    expected_evidence:   List[str]    # confirms hypothesis
    falsifying_evidence: List[str]    # rejects hypothesis
    max_iterations:      int = 3
