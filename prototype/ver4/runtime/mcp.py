"""MCP-backed runtime for deterministic discovery."""

import asyncio
import json
from typing import Any, Dict

from prototype.sub_agents.true_mcp_exec import run_mcp_tool
from prototype.ver4.runtime.base import RuntimeErrorResult


def _decode(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


class MCPRuntime:
    async def _call(self, tool: str, args: Dict[str, Any]) -> str:
        try:
            return await run_mcp_tool(tool, args)
        except Exception as exc:
            raise RuntimeErrorResult(f"MCP {tool} failed: {exc}") from exc

    async def network_scan(self, target: str) -> str:
        return await self._call("basic_scan", {"target": target})

    async def service_scan(self, target: str, ports: str) -> str:
        return await self._call("noping_version_scan", {"target": target, "ports": ports})

    async def http_request(self, method: str, url: str, max_body_size: int, max_redirects: int) -> Dict[str, Any]:
        result = await self._call(
            "http_request",
            {
                "method": method,
                "url": url,
                "follow_redirects": True,
                "max_body_size": max_body_size,
            },
        )
        decoded = _decode(result)
        if isinstance(decoded, dict):
            return decoded
        return {"body": str(decoded), "error": None, "redirects": []}

    async def content_scan(self, url: str, max_runtime: int) -> str:
        started = _decode(
            await self._call(
                "start_feroxbuster",
                {
                    "target": url,
                    "max_runtime": max_runtime,
                },
            )
        )
        if not isinstance(started, dict) or not started.get("task_id"):
            return str(started)

        task_id = started["task_id"]
        deadline = asyncio.get_running_loop().time() + max_runtime
        while asyncio.get_running_loop().time() < deadline:
            status = _decode(await self._call("get_task", {"task_id": task_id}))
            if isinstance(status, dict) and str(status.get("status", "")).lower() in {"completed", "finished", "failed", "error", "timeout"}:
                break
            await asyncio.sleep(1)

        output = await self._call("get_task_output_mcp", {"task_id": task_id})
        return output
