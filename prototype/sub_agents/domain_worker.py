# domain_worker.py
"""
CyberStrike v3 — Domain Worker Harness.

Domain Workers execute partition loops:
  Partition → Partition Planner (LLM) → Reviewer (LLM) → Executor → Extractor → Event Generator

The Dependency Orchestrator calls worker.execute(partition, knowledge).
The worker returns a WorkerResult containing knowledge updates and generated events.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Any, Protocol

from prototype.sub_agents.knowledge_partition import (
    KnowledgePartition,
    KnowledgeGraph,
    WorkerResult,
    PartitionStatus,
    void_knowledge,
    merge_kb,
)
from prototype.sub_agents.schemas import MasterState
from prototype.sub_agents.tactical_planner_module import tactical_planner, tactical_extractor
from prototype.sub_agents.plan_reviewer import plan_reviewer
from prototype.sub_agents.executor import execute_plan
from prototype.sub_agents.event_generator import generate_events
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))


class DomainWorker(Protocol):
    async def execute(
        self,
        partition: KnowledgePartition,
        knowledge: KnowledgeGraph,
    ) -> WorkerResult:
        ...


class BaseDomainWorker:
    """
    Standard worker that runs the tactical loop:
      Partition Planner → Reviewer → Executor → Extractor.
    """
    def __init__(self, domain: str, allowed_agents: List[str]):
        self.domain = domain
        self.allowed_agents = allowed_agents

    async def execute(
        self,
        partition: KnowledgePartition,
        knowledge: KnowledgeGraph,
    ) -> WorkerResult:
        logger.info(f"[{self.domain.upper()} WORKER] Starting partition: {partition.partition_id}")
        
        # 1. Setup local MasterState mimicking v2 but scoped to this partition
        local_state: MasterState = {
            "query":                 knowledge.get("query_target", ""),
            "current_phase":         self.domain,  # Partition Planner uses domain as phase
            "phase_objective":       partition.goal,
            "phase_iteration_count": 0,
            "knowledge":             knowledge,
            "plan":                  [],
            "execution_history":     [],
            "last_execution_results": [],
            "phase_history":         [],
            "_phase_summary":        "",
            "_extracted_knowledge":  void_knowledge(),
            "vuln_nudge":            None,
            "checked_vulns":         [],
            "final_answer":          "",
            "last_node":             "",
            "metrics":               {}
        }

        loop_count = 0
        max_loops = 5  # Safe guard loop limit

        accumulated_update = void_knowledge()

        while loop_count < max_loops:
            loop_count += 1
            logger.info(f"[{self.domain.upper()} WORKER] Loop {loop_count}/{max_loops}")

            # A. Plan next step(s)
            # We call tactical_planner synchronously. If it fails, plan will be empty
            logger.info(f"[{self.domain.upper()} WORKER] Calling Partition Planner...")
            local_state = tactical_planner(local_state)
            
            draft_plan = local_state.get("plan", [])
            if not draft_plan:
                logger.info(f"[{self.domain.upper()} WORKER] Partition Planner produced empty plan. Partition complete.")
                break

            # B. Review plan
            logger.info(f"[{self.domain.upper()} WORKER] Calling Plan Reviewer...")
            review_res = plan_reviewer(local_state)
            local_state["plan"] = review_res.get("plan", [])

            reviewed_plan = local_state.get("plan", [])
            if not reviewed_plan:
                logger.info(f"[{self.domain.upper()} WORKER] Plan Reviewer cleared all tasks. Complete.")
                break

            # C. Execute plan (async wrapper)
            logger.info(f"[{self.domain.upper()} WORKER] Executing plan: {reviewed_plan}")
            # run execute_plan in thread pool if sync or run directly
            loop = asyncio.get_running_loop()
            executions = await loop.run_in_executor(None, execute_plan, reviewed_plan, True)
            
            local_state["last_execution_results"] = executions
            local_state["execution_history"] = local_state.get("execution_history", []) + executions
            local_state["plan"] = []

            # D. Extract findings
            logger.info(f"[{self.domain.upper()} WORKER] Calling Extractor...")
            extractor_res = tactical_extractor(local_state)
            
            # Merge freshly extracted knowledge
            new_extract = extractor_res.get("_extracted_knowledge", void_knowledge())
            accumulated_update = merge_kb(accumulated_update, new_extract)

            # Update master knowledge for the next planning iteration
            local_state["knowledge"] = merge_kb(local_state["knowledge"], new_extract)
            local_state["_extracted_knowledge"] = void_knowledge()
            local_state["last_execution_results"] = []

        # 2. Diff knowledge and generate events
        events = generate_events(knowledge, merge_kb(knowledge, accumulated_update), source_partition=partition.partition_id)

        logger.info(f"[{self.domain.upper()} WORKER] Complete. Generated {len(events)} events.")
        
        return WorkerResult(
            partition_id=partition.partition_id,
            knowledge_update=accumulated_update,
            events=events,
            status="complete"
        )
