# dependency_orchestrator.py
"""
CyberStrike v3 — Dependency Orchestrator.

Manages execution of partitions based on their prerequisite status.
Runs without LLMs, purely on infrastructure and graph execution.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Set, Any

from prototype.sub_agents.knowledge_partition import (
    KnowledgePartition,
    KnowledgeGraph,
    WorkerResult,
    PartitionStatus,
    merge_kb,
)
from prototype.sub_agents.partition_definitions import PARTITION_DEFINITIONS
from prototype.sub_agents.domain_worker import BaseDomainWorker, DomainWorker
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))

# Registry of domain workers mapping to their allowed agents
WORKER_REGISTRY: Dict[str, DomainWorker] = {
    "network": BaseDomainWorker(domain="network", allowed_agents=["nmap_a"]),
    "http": BaseDomainWorker(domain="http", allowed_agents=["http_a", "ferox_a"]),
}


class DependencyOrchestrator:
    def __init__(self, max_concurrent: int = 4):
        self.definitions = PARTITION_DEFINITIONS
        self.partitions: Dict[str, KnowledgePartition] = {}
        self.max_concurrent = max_concurrent

    async def run(self, knowledge: KnowledgeGraph) -> KnowledgeGraph:
        """
        Main reactive loop: runs until no runnable partitions are pending or running.
        """
        logger.info("[orchestrator] Starting Dependency Orchestrator loop...")
        self.knowledge = knowledge

        while True:
            # 1. Evaluate partition matchers to discover new potential partitions
            self._discover_partitions(self.knowledge)

            # 2. Get runnable partitions (prerequisites satisfied, status = PENDING)
            runnable = self._get_runnable()
            running = self._get_by_status(PartitionStatus.RUNNING)
            complete = self._get_by_status(PartitionStatus.COMPLETE)

            current_state = (len(runnable), len(running), len(complete))
            if not hasattr(self, "_last_logged_state") or self._last_logged_state != current_state:
                logger.info(
                    f"[orchestrator] Status update: "
                    f"{current_state[0]} runnable, {current_state[1]} running, "
                    f"{current_state[2]} complete"
                )
                self._last_logged_state = current_state

            # 3. Stop if no runnable work and no running tasks
            if not runnable and not running:
                logger.info("[orchestrator] No runnable or running partitions remain. Loop complete.")
                break

            # 4. Spawn runnable partitions up to max_concurrent limit
            slots_available = self.max_concurrent - len(running)
            if slots_available > 0 and runnable:
                to_spawn = runnable[:slots_available]
                logger.info(f"[orchestrator] Spawning {len(to_spawn)} new partitions in parallel")
                
                # Mark as RUNNING immediately to avoid double spawning
                for p in to_spawn:
                    p.status = PartitionStatus.RUNNING

                # Start the async tasks
                for p in to_spawn:
                    asyncio.create_task(self._run_partition(p))

            # 5. Wait for any running partition to complete before checking again
            await asyncio.sleep(1)

        return self.knowledge

    def _discover_partitions(self, knowledge: KnowledgeGraph):
        """Evaluate definitions against the current knowledge base."""
        for definition in self.definitions:
            matches = definition.prerequisite_matcher(knowledge)
            for m in matches:
                target = m["target"]
                
                # Instantiate partition
                p = definition.instantiate(target, metadata=m)
                
                # Register if not a duplicate
                if p.partition_id not in self.partitions:
                    logger.info(f"[orchestrator] Registered new partition: {p.partition_id}")
                    self.partitions[p.partition_id] = p

    def _get_runnable(self) -> List[KnowledgePartition]:
        """Find pending partitions that can execute right now."""
        # For M1, prerequisites are evaluated by definitions' matchers,
        # so any pending partition in self.partitions is considered runnable.
        return [
            p for p in self.partitions.values()
            if p.status == PartitionStatus.PENDING
        ]

    def _get_by_status(self, status: PartitionStatus) -> List[KnowledgePartition]:
        return [p for p in self.partitions.values() if p.status == status]

    async def _run_partition(self, partition: KnowledgePartition):
        """Execute one partition via the corresponding DomainWorker."""
        domain = partition.domain
        if domain not in WORKER_REGISTRY:
            logger.error(f"[orchestrator] No worker registered for domain: {domain}")
            partition.status = PartitionStatus.FAILED
            return

        worker = WORKER_REGISTRY[domain]
        try:
            # Execute worker logic (contains the planner-reviewer-executor-extractor loop)
            result = await worker.execute(partition, self.knowledge)
            
            # Merge returned knowledge updates back into the master graph
            self.knowledge = merge_kb(self.knowledge, result.knowledge_update)
            
            partition.status = PartitionStatus.COMPLETE
            logger.info(f"[orchestrator] Partition {partition.partition_id} finished successfully")
            
        except Exception as e:
            logger.exception(f"[orchestrator] Partition {partition.partition_id} failed with error: {e}")
            partition.status = PartitionStatus.FAILED
