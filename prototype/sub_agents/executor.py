# executor.py
"""
Agent execution layer.
Maps agent names to their LangGraph instances and executes tasks,
extracting clean result strings for the planners.
"""

import asyncio
import json
from typing import Dict, List

# Agent imports
from prototype.sub_agents.curl_graph_test_mcp import graph as curl_a
from prototype.sub_agents.nmap_graph_test_mcp import graph as nmap_a
from prototype.sub_agents.ferox_graph_test_mcp import graph as ferox_a
from prototype.sub_agents.python_req_graph_test_mcp import graph as python_a
from prototype.sub_agents.xss_graph_test_mcp import graph as xss_a
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))

AGENT_MAP = {
    "nmap_a": nmap_a,
    "curl_a": curl_a,
    "ferox_a": ferox_a,
    "python_a": python_a,
    "xss_a": xss_a,
}


def extract_agent_message(result: dict) -> str:
    """Extract message from agent graph result."""
    try:
        data = result["messages"][-1].content
        loaded = json.loads(data)
        return loaded.get("message", "No message in response")
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.warning(f"Warning: Failed to extract message - {e}")
        return f"Error extracting response: {str(e)}"


async def execute_agent_async(agent_graph, task: str) -> str:
    """Execute agent asynchronously and extract result."""
    try:
        result = await agent_graph.ainvoke({
            "task": task,
            "messages": [],
            "tool_used": []
        })
        return extract_agent_message(result)
    except Exception as e:
        return f"Agent execution failed: {str(e)}"


def execute_agent(agent_name: str, task: str) -> str:
    """
    Execute agent by name synchronously.

    Args:
        agent_name: One of 'nmap_a', 'curl_a', 'ferox_a', 'xss_a', 'python_a'
        task: Task description for the agent

    Returns:
        Agent's response message
    """
    if agent_name not in AGENT_MAP:
        return f"Unknown agent: {agent_name}"

    return asyncio.run(execute_agent_async(AGENT_MAP[agent_name], task))


def execute_plan(plan: List[dict], verbose: bool = True) -> List[Dict[str, str]]:
    """
    Execute all tasks in a plan.

    Args:
        plan: List of task dicts with 'agent' and 'task_description'
        verbose: log execution progress

    Returns:
        List of execution records with agent, task, and result
    """
    executions = []

    for i, task in enumerate(plan, 1):
        agent = task["agent"]
        desc = task["task_description"]

        if verbose:
            task_preview = desc if len(desc) <= 300 else desc[:300] + "..."
            logger.info(f"[{i}/{len(plan)}] Executing {agent}: {task_preview}")

        response = execute_agent(agent, desc)

        executions.append({
            "agent": agent,
            "task": desc,
            "result": response
        })

        if verbose:
            preview = response[:300] + "..." if len(response) > 300 else response
            logger.info(f"Result preview: {preview}")

    return executions