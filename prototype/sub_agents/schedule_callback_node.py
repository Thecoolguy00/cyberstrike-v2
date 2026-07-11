"""
schedule_callback_node.py — Non-blocking graph node that registers
a background task callback and exits the graph immediately.

The node NEVER waits. It schedules work and returns END.

Usage in agent graphs:
    from prototype.sub_agents.schedule_callback_node import make_schedule_callback_node
    flow.add_node("schedule_callback", make_schedule_callback_node("nmap_a"))
    flow.add_edge("schedule_callback", END)
"""

import json

from langchain_core.messages import AIMessage

from prototype.sub_agents.task_callback_scheduler import get_scheduler

# Default check interval per tool type (minutes)
DEFAULT_CHECK_INTERVALS = {
    "start_nmap_long_scan": 3,   # nmap full scans take a while
    "start_feroxbuster": 2,      # feroxbuster is typically faster
}
DEFAULT_INTERVAL = 2  # fallback for unknown tools


def make_schedule_callback_node(agent_name: str):
    """
    Factory that creates a schedule_callback node bound to a specific agent.

    The node reads _bg_task_info from state (set by mcp_exec_node),
    registers a callback with the scheduler, and returns a final message.
    The graph then exits (schedule_callback → END).

    Args:
        agent_name: "nmap_a", "ferox_a", etc. — stored so the scheduler
                    knows which agent to re-invoke on callback.
    """
    async def schedule_callback_node(state):
        bg_info = state.get("_bg_task_info")
        if not bg_info or not bg_info.get("task_id"):
            # Shouldn't happen if routing is correct, but be safe
            return {
                "messages": [AIMessage(content=json.dumps({
                    "message": "Error: no background task info found in state"
                }))],
                "_bg_task_info": None,
            }

        task_id = bg_info["task_id"]
        tool_name = bg_info.get("tool", "")

        # Determine check interval from the tool that started the task
        timeout_minutes = DEFAULT_CHECK_INTERVALS.get(tool_name, DEFAULT_INTERVAL)

        # Register callback — returns immediately
        scheduler = get_scheduler()
        scheduler.schedule_callback(
            task_id=task_id,
            timeout_minutes=timeout_minutes,
            agent_name=agent_name,
            original_task_desc=state.get("task", ""),
            tool_name=tool_name,
        )

        # Return a message for the execution history and clear the flag
        return {
            "messages": [AIMessage(content=json.dumps({
                "message": (
                    f"Background task {task_id} started. "
                    f"Callback scheduled in {timeout_minutes} minutes. "
                    f"This agent will be re-invoked with results."
                ),
                "task_id": task_id,
                "callback_scheduled": True,
                "check_interval_minutes": timeout_minutes,
            }))],
            "_bg_task_info": None,  # clear the flag
        }

    return schedule_callback_node
