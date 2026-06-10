"""
Master orchestrator for penetration testing agents.
Implements iterative plan-execute-replan loop.
"""

import asyncio
import json
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Agent imports
from prototype.sub_agents.curl_graph_test_mcp import graph as curl_a
from prototype.sub_agents.nmap_graph_test_mcp import graph as nmap_a
from prototype.sub_agents.ferox_graph_test_mcp import graph as ferox_a
from prototype.sub_agents.python_req_graph_test_mcp import graph as python_a
from prototype.sub_agents.xss_graph_test_mcp import graph as xss_a
from prototype.sub_agents.plan0 import plan_next_step
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))

load_dotenv()

# ============= Agent Execution Layer =============

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
        agent_name: One of 'nmap_a', 'curl_a', 'ferox_a', 'xss_a', python_a
        task: Task description for the agent
    
    Returns:
        Agent's response message
    """
    agent_map = {
        "nmap_a": nmap_a,
        "curl_a": curl_a,
        "ferox_a": ferox_a,
        "python_a": python_a,
        "xss_a": xss_a
    }
    
    if agent_name not in agent_map:
        return f"Unknown agent: {agent_name}"
    
    return asyncio.run(execute_agent_async(agent_map[agent_name], task))


# ============= Orchestration Layer =============

def execute_plan(plan: List[dict], verbose: bool = True) -> List[Dict[str, str]]:
    """
    Execute all tasks in a plan.
    
    Args:
        plan: List of task dicts with 'agent' and 'task_description'
        verbose: logger.info execution progress
    
    Returns:
        List of execution records with agent, task, and result
    """
    executions = []
    
    for i, task in enumerate(plan, 1):
        agent = task["agent"]
        desc = task["task_description"]
        
        if verbose:
            # Log a single condensed line with agent and task preview to avoid redundant lines
            task_preview = desc if len(desc) <= 300 else desc[:300] + "..."
            logger.info(f"[{i}/{len(plan)}] Executing {agent}: {task_preview}")
        
        response = execute_agent(agent, desc)
        
        # Store execution record
        executions.append({
            "agent": agent,
            "task": desc,
            "result": response
        })
        
        if verbose:
            preview = response[:300] + "..." if len(response) > 300 else response
            logger.info(f"Result preview: {preview}")
    
    return executions


def format_execution_history(executions: List[Dict[str, str]]) -> str:
    """
    Format execution history for planner with clear task-result mapping.
    
    Args:
        executions: List of execution records
    
    Returns:
        Formatted string showing each task and its result
    """
    if not executions:
        return "No executions yet"
    
    formatted = []
    for i, ex in enumerate(executions, 1):
        result_preview = ex["result"][:200] + "..." if len(ex["result"]) > 200 else ex["result"]
        formatted.append(
            f"{i}. [{ex['agent']}] {ex['task']}\n"
            f"   Result: {result_preview}"
        )
    
    return "\n\n".join(formatted)


def run_master_loop(query: str, max_iterations: int = 20, verbose: bool = True):
    """
    Main orchestration loop.
    
    Args:
        query: Penetration testing objective
        max_iterations: Safety limit for planning cycles
        verbose: logger.info detailed progress
    
    Returns:
        Final answer from planner
    """
    if verbose:
        logger.info(f"OBJECTIVE: {query}")
    
    # State tracking - use execution history instead of separate dicts
    execution_history = []  # List of {agent, task, result}
    iteration = 0
    
    # Initial plan
    plan_result = plan_next_step(query=query)
    
    while iteration < max_iterations:
        iteration += 1
        
        # Check if done
        if plan_result["is_complete"]:
            if verbose:
                logger.info(f"Final Answer: {plan_result['final_answer']}")
            return plan_result["final_answer"]
        
        current_plan = plan_result["plan"]
        
        if not current_plan:
            logger.warning("Warning: Empty plan but not marked complete. Stopping.")
            break
        
        if verbose:
            logger.info(f"Iteration {iteration}, Tasks to execute: {len(current_plan)}")
        
        # Execute current plan
        new_executions = execute_plan(current_plan, verbose=verbose)
        
        # Add to history
        execution_history.extend(new_executions)
        
        # Replan with updated history
        plan_result = plan_next_step(
            query=query,
            execution_history=execution_history  # Pass full history
        )
    
    # Max iterations reached
    logger.info(f"Warning: Reached max iterations ({max_iterations})")
    return plan_result.get("final_answer", "Incomplete - max iterations reached")


# ============= Entry Point =============

def main():
    """Run the master orchestrator."""
    query = "Try to find as much info on target 10.49.148.67"
    
    try:
        final_answer = run_master_loop(
            query=query,
            max_iterations=25,
            verbose=True
        )
        
        logger.info(f"Execution complete, final answer: \n {final_answer}")
    except KeyboardInterrupt:
        print("graceful shutdown")


if __name__ == "__main__":
    main()