# executor.py
"""
Agent execution layer.
Supports parallel execution of independent tasks using asyncio.gather.
Tasks with depends_on run only after their upstream tasks complete.

Also processes completed background task callbacks from the scheduler
at the start of each execution cycle.
"""

import asyncio
import json
from typing import Dict, List

from prototype.sub_agents.curl_graph_test_mcp       import graph as curl_a
from prototype.sub_agents.nmap_graph_test_mcp       import graph as nmap_a
from prototype.sub_agents.ferox_graph_test_mcp      import graph as ferox_a
from prototype.sub_agents.python_req_graph_test_mcp import graph as python_a
from prototype.sub_agents.xss_graph_test_mcp        import graph as xss_a
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))

AGENT_MAP = {
    "nmap_a":   nmap_a,
    "curl_a":   curl_a,
    "ferox_a":  ferox_a,
    "python_a": python_a,
    "xss_a":    xss_a,
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
        msg = _extract_agent_message(result)

        # Check if this was a background task scheduling (graph exited via schedule_callback → END)
        try:
            parsed = json.loads(msg)
            if parsed.get("callback_scheduled"):
                return (
                    f"Background task {parsed.get('task_id', '?')} started. "
                    f"Results will be available in ~{parsed.get('check_interval_minutes', '?')} minutes."
                )
        except (json.JSONDecodeError, KeyError):
            pass

        return msg
    except Exception as e:
        return f"Agent execution failed: {str(e)}"


def _build_callback_prompt(callback_result: dict) -> str:
    """
    Build a task prompt that includes the background task results
    for agent re-invocation. The scheduler stores no session state,
    so we rebuild a fresh prompt from the original description + MCP output.
    """
    status = callback_result.get("status", {})
    original_task = callback_result.get("original_task_desc", "")

    return (
        f"{original_task}\n\n"
        f"--- BACKGROUND TASK RESULT ---\n"
        f"Task ID: {callback_result.get('task_id', 'unknown')}\n"
        f"Status: {status.get('status', 'unknown')}\n"
        f"Runtime: {status.get('runtime_seconds', '?')}s\n"
        f"Output:\n{status.get('output', 'No output available')}\n"
        f"---\n\n"
        f"Process the above background task results and provide your analysis."
    )


async def execute_plan_parallel(plan: List[dict], verbose: bool = True) -> List[Dict[str, str]]:
    """
    Execute a plan respecting task dependencies.

    Before executing the plan, drains the scheduler's callback result
    queue and re-invokes agents with completed background task results.

    Algorithm:
    1. Process any completed background task callbacks.
    2. Build a set of completed task_ids.
    3. Each iteration: collect all tasks whose depends_on are fully in
       completed — these are the "ready" layer.
    4. Run the ready layer concurrently with asyncio.gather.
    5. Repeat until all tasks are done or a deadlock is detected.

    Tasks without a task_id (legacy format) are assigned a generated id
    and treated as having no dependencies so they all run in one parallel batch.
    """
    # ── Process completed background task callbacks ──
    from prototype.sub_agents.task_callback_scheduler import get_scheduler

    scheduler = get_scheduler()
    callback_results = scheduler.get_completed_results()
    callback_execution_results = []

    for cb in callback_results:
        agent_name = cb.get("agent_name", "")
        task_id = cb.get("task_id", "")

        if verbose:
            logger.info(
                f"[executor] Processing background task callback: "
                f"task={task_id}, agent={agent_name}"
            )

        if agent_name in AGENT_MAP:
            # Rebuild task prompt with background results and re-invoke agent
            callback_prompt = _build_callback_prompt(cb)

            if verbose:
                logger.info(f"  → [callback:{agent_name}] re-invoking with bg task results")

            result = await _run_agent(AGENT_MAP[agent_name], callback_prompt)

            if verbose:
                logger.info(f"  ← [callback:{agent_name}] {result[:200]}")

            callback_execution_results.append({
                "agent": agent_name,
                "task": callback_prompt,
                "result": result,
            })
        else:
            logger.warning(f"[executor] Unknown agent in callback: {agent_name}")
            callback_execution_results.append({
                "agent": agent_name,
                "task": f"bg_callback:{task_id}",
                "result": f"Unknown agent: {agent_name}",
            })

    # ── Execute the current plan ──
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
            if agent not in AGENT_MAP:
                result = f"Unknown agent: {agent}"
            else:
                if verbose:
                    logger.info(f"  → [{agent}] {desc[:200]}")
                result = await _run_agent(AGENT_MAP[agent], desc)
                if verbose:
                    logger.info(f"  ← [{agent}] {result[:200]}")
            return {"agent": agent, "task": desc, "result": result, "_task_id": task["task_id"]}

        batch_results = await asyncio.gather(*[_run_one(t) for t in ready])

        for br in batch_results:
            task_id = br.pop("_task_id")
            completed[task_id] = br["result"]
            results.append(br)

        done_ids = {t["task_id"] for t in ready}
        remaining = [t for t in remaining if t["task_id"] not in done_ids]

    return callback_execution_results + results


def execute_plan(plan: List[dict], verbose: bool = True) -> List[Dict[str, str]]:
    """
    Synchronous entry point — wraps execute_plan_parallel.
    Called by the LangGraph execute_node which runs in a sync context.
    """
    return asyncio.run(execute_plan_parallel(plan, verbose=verbose))