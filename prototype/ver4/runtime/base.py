"""Transport-neutral runtime contract."""

from typing import Any, Dict, Protocol


class DiscoveryRuntime(Protocol):
    async def network_scan(self, target: str, ports: list[str] | None = None) -> str: ...

    async def service_scan(self, target: str, ports: str) -> str: ...

    async def http_request(self, method: str, url: str, max_body_size: int, max_redirects: int, timeout: int = 5, verify_ssl: bool = True) -> Dict[str, Any]: ...

    async def content_scan(self, url: str) -> str: ...


class RuntimeErrorResult(Exception):
    """Raised when a runtime operation cannot be completed."""
