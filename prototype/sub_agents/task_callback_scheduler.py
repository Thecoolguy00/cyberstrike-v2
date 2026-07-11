"""
task_callback_scheduler.py — Non-blocking background task callback system.

Runs a dedicated daemon thread with an asyncio event loop.
When a timer fires: checks MCP task status, stores results in a
thread-safe queue for the executor to pick up.

The scheduler stores NO session state — only lightweight metadata
(task_id, agent_name, original_task, tool_name). A fresh agent state
is rebuilt from original_task_desc + MCP results at callback time.
"""

import asyncio
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from prototype.sub_agents.true_mcp_exec import run_mcp_tool
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))


@dataclass
class CallbackEntry:
    """Lightweight entry for a pending background task callback."""
    task_id: str
    timeout_minutes: int          # 1-6 (clamped)
    agent_name: str               # "nmap_a", "ferox_a" etc.
    original_task_desc: str       # the task description the agent was working on
    tool_name: str                # "start_nmap_long_scan", "start_feroxbuster", etc.
    scheduled_at: float = field(default_factory=time.time)
    check_count: int = 0          # how many times we've checked so far
    max_checks: int = 5           # stop re-checking after this many
    timer_handle: Optional[asyncio.TimerHandle] = None


class TaskCallbackScheduler:
    """
    Non-blocking scheduler for MCP background task callbacks.

    - Runs on a dedicated daemon thread with its own event loop
    - schedule_callback() registers a timer and returns immediately
    - When timer fires: checks MCP status via check_mcp_task_status
    - If task completed: stores result in callback_results queue
    - If task still running: re-schedules automatically (up to max_checks)
    - Executor polls callback_results at the start of each cycle
    """

    def __init__(self):
        self._pending: Dict[str, CallbackEntry] = {}
        self._results: queue.Queue = queue.Queue()  # thread-safe
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()  # protects _pending from cross-thread access
        self._started = False

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self):
        """Start the background event loop thread."""
        if self._started:
            return

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="task-callback-scheduler",
        )
        self._thread.start()
        self._started = True
        logger.info("[scheduler] Background callback scheduler started")

    def _run_loop(self):
        """Runs in the daemon thread — keeps the event loop alive."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def stop(self):
        """Stop the scheduler (for clean shutdown)."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        self._started = False
        logger.info("[scheduler] Background callback scheduler stopped")

    # ── Public API ─────────────────────────────────────────────────────────

    def schedule_callback(
        self,
        task_id: str,
        timeout_minutes: int,
        agent_name: str,
        original_task_desc: str,
        tool_name: str,
    ) -> dict:
        """
        Register a delayed callback for a background task.
        Returns immediately. Called from ScheduleCallbackNode (may be sync context).

        Args:
            task_id: Background task ID from MCP
            timeout_minutes: Minutes to wait before first check (clamped to [1, 6])
            agent_name: Which agent to re-invoke ("nmap_a", "ferox_a", etc.)
            original_task_desc: The task description for re-invocation
            tool_name: The MCP tool that started the background task
        """
        if not self._started:
            self.start()

        # Clamp timeout to [1, 6]
        timeout_minutes = max(1, min(6, timeout_minutes))

        entry = CallbackEntry(
            task_id=task_id,
            timeout_minutes=timeout_minutes,
            agent_name=agent_name,
            original_task_desc=original_task_desc,
            tool_name=tool_name,
        )

        with self._lock:
            # Cancel existing callback for this task_id if any
            if task_id in self._pending:
                old = self._pending[task_id]
                if old.timer_handle:
                    old.timer_handle.cancel()

            self._pending[task_id] = entry

        # Schedule the timer on the event loop thread
        delay_seconds = timeout_minutes * 60

        def _schedule_on_loop():
            handle = self._loop.call_later(
                delay_seconds,
                lambda: asyncio.ensure_future(
                    self._on_timer_fire(task_id),
                    loop=self._loop
                ),
            )
            with self._lock:
                if task_id in self._pending:
                    self._pending[task_id].timer_handle = handle

        self._loop.call_soon_threadsafe(_schedule_on_loop)

        logger.info(
            f"[scheduler] Callback scheduled: task={task_id}, "
            f"agent={agent_name}, check_in={timeout_minutes}min"
        )

        return {
            "task_id": task_id,
            "scheduled": True,
            "check_in_minutes": timeout_minutes,
        }

    def cancel_callback(self, task_id: str) -> bool:
        """
        Cancel a pending callback (does NOT cancel the MCP task itself).
        Returns True if a callback was found and cancelled.
        """
        with self._lock:
            entry = self._pending.pop(task_id, None)

        if entry:
            if entry.timer_handle:
                entry.timer_handle.cancel()
            logger.info(f"[scheduler] Callback cancelled: task={task_id}")
            return True

        return False

    def get_completed_results(self) -> List[dict]:
        """
        Drain the results queue. Called by the executor at the start
        of each plan execution cycle. Non-blocking.
        """
        results = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                break
        return results

    def get_pending_callbacks(self) -> List[dict]:
        """List currently pending callbacks (for debugging/status)."""
        with self._lock:
            return [
                {
                    "task_id": e.task_id,
                    "agent_name": e.agent_name,
                    "tool_name": e.tool_name,
                    "timeout_minutes": e.timeout_minutes,
                    "check_count": e.check_count,
                    "max_checks": e.max_checks,
                    "scheduled_at": e.scheduled_at,
                    "waiting_seconds": int(time.time() - e.scheduled_at),
                }
                for e in self._pending.values()
            ]

    # ── Internal (runs on scheduler's event loop) ──────────────────────────

    async def _on_timer_fire(self, task_id: str):
        """
        Timer expired. Check MCP task status.
        If completed → queue result.
        If still running → re-schedule (if under max_checks).
        """
        with self._lock:
            entry = self._pending.get(task_id)
            if not entry:
                return  # was cancelled

        entry.check_count += 1

        logger.info(
            f"[scheduler] Timer fired: task={task_id}, "
            f"check #{entry.check_count}/{entry.max_checks}"
        )

        # Check MCP task status
        status = await self._check_mcp_status(task_id)

        if status.get("completed") or status.get("status") == "not_found":
            # Task done (or disappeared) — queue result for executor
            self._results.put({
                "task_id": task_id,
                "agent_name": entry.agent_name,
                "original_task_desc": entry.original_task_desc,
                "tool_name": entry.tool_name,
                "status": status,
                "completed_at": time.time(),
                "checks_performed": entry.check_count,
            })

            with self._lock:
                self._pending.pop(task_id, None)

            logger.info(
                f"[scheduler] Task completed: task={task_id}, "
                f"status={status.get('status')}"
            )

        elif entry.check_count >= entry.max_checks:
            # Give up — queue partial result
            status["output"] = (status.get("output", "") +
                                "\n[SCHEDULER] Max checks reached, returning partial output")

            self._results.put({
                "task_id": task_id,
                "agent_name": entry.agent_name,
                "original_task_desc": entry.original_task_desc,
                "tool_name": entry.tool_name,
                "status": status,
                "completed_at": time.time(),
                "checks_performed": entry.check_count,
                "max_checks_exceeded": True,
            })

            with self._lock:
                self._pending.pop(task_id, None)

            # Also cancel the MCP task since we're giving up
            try:
                await run_mcp_tool("cancel_mcp_task", {"task_id": task_id})
            except Exception as e:
                logger.warning(f"[scheduler] Failed to cancel timed-out task {task_id}: {e}")

            logger.warning(
                f"[scheduler] Max checks exceeded: task={task_id}, "
                f"cancelling MCP task"
            )

        else:
            # Still running — re-schedule with same interval
            delay_seconds = entry.timeout_minutes * 60

            handle = self._loop.call_later(
                delay_seconds,
                lambda tid=task_id: asyncio.ensure_future(
                    self._on_timer_fire(tid),
                    loop=self._loop
                ),
            )

            with self._lock:
                if task_id in self._pending:
                    self._pending[task_id].timer_handle = handle

            logger.info(
                f"[scheduler] Task still running: task={task_id}, "
                f"re-checking in {entry.timeout_minutes}min"
            )

    async def _check_mcp_status(self, task_id: str) -> dict:
        """Call check_mcp_task_status via MCP, parse and return status dict."""
        try:
            raw = await run_mcp_tool("check_mcp_task_status", {"task_id": task_id})
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"[scheduler] Could not parse MCP status for {task_id}: {raw[:200]}")
            return {
                "task_id": task_id,
                "status": "error",
                "completed": False,
                "output": f"Failed to parse MCP response: {raw[:500]}",
            }
        except Exception as e:
            logger.error(f"[scheduler] MCP status check failed for {task_id}: {e}")
            return {
                "task_id": task_id,
                "status": "error",
                "completed": False,
                "output": f"MCP status check error: {str(e)}",
            }


# ── Singleton ──────────────────────────────────────────────────────────────────

_scheduler: Optional[TaskCallbackScheduler] = None


def get_scheduler() -> TaskCallbackScheduler:
    """Returns the global TaskCallbackScheduler, creating it if needed."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskCallbackScheduler()
        _scheduler.start()
    return _scheduler
