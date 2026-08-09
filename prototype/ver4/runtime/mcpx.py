"""MCP-backed runtime for deterministic discovery."""

import json
from typing import Any, Dict

from prototype.sub_agents.true_mcp_exec import run_mcp_tool
from prototype.ver4.constants import DEFAULT_HTTP_TIMEOUT
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

    async def network_scan(self, target: str, ports: list[str] | None = None) -> str:
        if ports:
            return await self._call("noping_version_scan", {"target": target, "ports": ports})
        return await self._call("basic_scan", {"target": target})

    async def service_scan(self, target: str, ports: str) -> str:
        return await self._call("noping_version_scan", {"target": target, "ports": ports})

    async def http_request(self, method: str, url: str, max_body_size: int, max_redirects: int, timeout: int = DEFAULT_HTTP_TIMEOUT, verify_ssl: bool = True) -> Dict[str, Any]:
        result = await self._call(
            "http_request",
            {
                "method": method,
                "url": url,
                "follow_redirects": True,
                "max_body_size": max_body_size,
                "timeout": timeout,
                "verify_ssl": verify_ssl,
            },
        )
        decoded = _decode(result)
        if isinstance(decoded, dict):
            return decoded
        return {"body": str(decoded), "error": None, "redirects": []}

    async def content_scan(self, url: str) -> str:
        return await self._call("foreground_feroxbuster", {"target": url})

    async def start_long_port_scan(self, target: str, ports: str, max_runtime: int = 900) -> Dict[str, Any]:
        decoded = _decode(await self._call("start_nmap_long_scan", {"target": target, "ports": ports, "max_runtime": max_runtime}))
        if isinstance(decoded, dict):
            return decoded
        return {"output": str(decoded)}

    async def get_task(self, task_id: str) -> Dict[str, Any]:
        decoded = _decode(await self._call("get_task", {"task_id": task_id}))
        if isinstance(decoded, dict):
            return decoded
        return {"output": str(decoded)}

    async def get_task_output(self, task_id: str) -> str:
        return await self._call("get_task_output_mcp", {"task_id": task_id})
