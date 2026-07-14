# executor.py
"""
Agent execution layer.
Supports parallel execution of independent tasks using asyncio.gather.
Tasks with depends_on run only after their upstream tasks complete.
"""

import asyncio
import json
from typing import Dict, List

from prototype.sub_agents.http_graph              import graph as http_a
from prototype.sub_agents.nmap_graph_test_mcp       import graph as nmap_a
from prototype.sub_agents.ferox_graph_test_mcp      import graph as ferox_a
from prototype.sub_agents.python_req_graph_test_mcp import graph as python_a
from prototype.sub_agents.xss_graph_test_mcp        import graph as xss_a
from prototype.sub_agents.exploit_intel_graph       import graph as intel_a
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))

AGENT_MAP = {
    "nmap_a":   nmap_a,
    "http_a":   http_a,
    "ferox_a":  ferox_a,
    "python_a": python_a,
    "xss_a":    xss_a,
    "intel_a":  intel_a,
}


def _extract_agent_message(result: dict) -> str:
    try:
        data   = result["messages"][-1].content
        loaded = json.loads(data)
        return loaded.get("message", "No message in response")
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to extract agent message: {e}")
        return f"Error extracting response: {str(e)}"


async def _run_agent(agent_graph, task: str) -> str:
    try:
        result = await agent_graph.ainvoke({
            "task":      task,
            "messages":  [],
            "tool_used": [],
        })
        return _extract_agent_message(result)
    except Exception as e:
        return f"Agent execution failed: {str(e)}"


async def execute_plan_parallel(plan: List[dict], verbose: bool = True) -> List[Dict[str, str]]:
    """
    Execute a plan respecting task dependencies.

    Algorithm:
    1. Build a set of completed task_ids.
    2. Each iteration: collect all tasks whose depends_on are fully in
       completed — these are the "ready" layer.
    3. Run the ready layer concurrently with asyncio.gather.
    4. Repeat until all tasks are done or a deadlock is detected.

    Tasks without a task_id (legacy format) are assigned a generated id
    and treated as having no dependencies so they all run in one parallel batch.
    """
    # Normalise — assign task_ids to tasks that are missing one (backward compat)
    normalised = []
    for i, t in enumerate(plan):
        task = dict(t)
        if not task.get("task_id"):
            task["task_id"] = f"task_{i}"
        if "depends_on" not in task:
            task["depends_on"] = []
        normalised.append(task)

    completed: Dict[str, str] = {}   # task_id → result string
    results:   List[Dict[str, str]] = []
    remaining  = list(normalised)

    while remaining:
        ready = [
            t for t in remaining
            if all(dep in completed for dep in t.get("depends_on", []))
        ]

        if not ready:
            # deadlock — circular deps or missing dep; run first task to unblock
            logger.warning("[executor] Dependency deadlock — forcing first remaining task")
            ready = [remaining[0]]

        if verbose:
            agents = [t["agent"] for t in ready]
            logger.info(
                f"[executor] Running {len(ready)} task(s) in parallel: {agents}"
            )

        async def _run_one(task: dict) -> Dict[str, str]:
            agent = task["agent"]
            desc  = task["task_description"]
            
            # Inject dependency outputs to provide target/results context
            deps = task.get("depends_on", [])
            if deps:
                dep_context = []
                for dep_id in deps:
                    if dep_id in completed:
                        dep_context.append(f"Result of '{dep_id}': {completed[dep_id]}")
                if dep_context:
                    desc = desc + "\n\nContext from prerequisites:\n" + "\n".join(dep_context)
            
            status = "SUCCESS"
            if agent not in AGENT_MAP:
                result = f"Unknown agent: {agent}"
                status = "FAILED"
            else:
                if verbose:
                    logger.info(f"  -> [{agent}] {desc[:200]}")
                try:
                    result = await _run_agent(AGENT_MAP[agent], desc)
                    if "execution failed" in result.lower():
                        status = "FAILED"
                except Exception as e:
                    result = f"Agent execution failed: {str(e)}"
                    status = "FAILED"
                if verbose:
                    logger.info(f"  <- [{agent}] {result[:200]}")
            return {
                "agent": agent,
                "task": desc,
                "result": result,
                "_task_id": task["task_id"],
                "status": status,
                "coverage_keys": task.get("coverage_keys", [])
            }

        batch_results = await asyncio.gather(*[_run_one(t) for t in ready])

        for br in batch_results:
            task_id = br.pop("_task_id")
            completed[task_id] = br["result"]
            results.append(br)

        done_ids = {t["task_id"] for t in ready}
        remaining = [t for t in remaining if t["task_id"] not in done_ids]

    return results


def execute_plan(plan: List[dict], verbose: bool = True) -> List[Dict[str, str]]:
    """
    Synchronous entry point — wraps execute_plan_parallel.
    Called by the LangGraph execute_node which runs in a sync context.
    """
    return asyncio.run(execute_plan_parallel(plan, verbose=verbose))