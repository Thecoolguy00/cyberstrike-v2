from mcp.server.fastmcp import FastMCP
from typing import Dict, List, Sequence, Union, Optional

mcp=FastMCP(name="combined_tools",host="0.0.0.0",port=4545)

#nmap for network scan
from prototype.mcp_stuff.nmap_actions import (
    basic_scan_action,
    script_scan_action,
    aggressive_scan_action,
    noping_version_scan_action,
    start_nmap_long_scan_action,
)

#helper fucntion for normalising ports

def normalize_ports(ports: Optional[Union[str, List[str]]]) -> List[str]:
    """
    Fixes type shape
    Converts:
    "1-1000" → ["1-1000"]
    None → []
    Guarantees List[str]
    """
    if not ports:
        return []
    if isinstance(ports, str):
        return [ports]
    return ports

def is_large_port_range(p: str, max_span: int = 5000) -> bool:
    """Checks if the port range is larger than the allowed range"""
    if "-" not in p:
        return False
    try:
        start, end = map(int, p.split("-", 1))
        return (end - start) > max_span
    except ValueError:
        return False


@mcp.tool()
def basic_scan(target: str) ->str:
    """Perform a basic network scan using nmap's default port set.

    This runs ``nmap <target>`` without a ``-p`` option, so nmap checks its
    default top 1000 TCP ports. Use ``noping_version_scan`` or
    ``aggressive_scan`` when a specific port or range is required. Use
    ``start_nmap_long_scan`` with ``ports="1-65535"`` for a complete TCP
    port sweep.

    Args:
        target (str): Target IP address or hostname. Only scan systems you
            are authorized to assess.

    Returns:
        str: The output results of the basic scan.
    """
    return basic_scan_action(target)

@mcp.tool()
def aggressive_scan(target: str, ports: Optional[Union[str, List[str]]] = None) -> str:
    """Run an aggressive nmap scan with OS, service, script, and traceroute detection.

    Uses ``-T4 -A``. If ``ports`` is omitted, nmap uses its default top 1000
    TCP ports. Foreground scans must not request a range larger than 5000
    ports. For a full 1-65535 scan, use ``start_nmap_long_scan`` instead.

    Args:
        target (str): Target IP address or hostname. Only scan systems you
            are authorized to assess.
        ports (str | list[str], optional): Port expression, such as ``"80"``,
            ``"22,80,443"``, or ``"1-5000"``. Foreground ranges are limited
            to 5000 ports.

    Returns:
        str: The output results of the intense scan.
    """
    ports = normalize_ports(ports)

    for p in ports:
        if is_large_port_range(p):
            return "error: port ranges larger than 5000 are not allowed in foreground scans"
        
    return aggressive_scan_action(target,ports)

@mcp.tool()
def noping_version_scan(target: str, ports: Optional[Union[str, List[str]]] = None) -> str:
    """Detect services and versions without host discovery ping.

    Uses ``-Pn -sV`` and is useful when ICMP or host discovery is blocked. If
    ``ports`` is omitted, nmap uses its default top 1000 TCP ports. Foreground
    scans may specify a range of up to 5000 ports. Use
    ``start_nmap_long_scan`` with ``ports="1-65535"`` for all TCP ports.

    Args:
        target (str): Target IP address or hostname. Only scan systems you
            are authorized to assess.
        ports (str | list[str], optional): Port expression, such as ``"80"``,
            ``"22,80,443"``, or ``"1-5000"``. Foreground ranges are limited
            to 5000 ports.

    Returns:
        str: The output results of the recommended scan.
    """
    ports = normalize_ports(ports)

    for p in ports:
        if is_large_port_range(p):
            return "error: port ranges larger than 5000 are not allowed in foreground scans"

    return noping_version_scan_action(target,ports)

@mcp.tool()
def script_scan(target: str, script: str, ports: Optional[Union[str, List[str]]] = None) -> str:
    """Run a specified nmap NSE script against known target ports.

    Uses ``-sV --script=<script>``. Provide specific discovered ports rather
    than using this tool for initial port discovery. Foreground scans must not
    request a range larger than 5000 ports. Use
    ``start_nmap_long_scan`` for a full 1-65535 port discovery scan first.

    Args:
        target (str): Target IP address or hostname. Only scan systems you
            are authorized to assess.
        script (str): NSE script name or script expression to run.
        ports (str | list[str], optional): Known port expression, such as
            ``"80"`` or ``"22,80,443"``. Foreground ranges are limited to
            5000 ports.

    Returns:
        str: The output results of the script scan.
    """
    ports = normalize_ports(ports)

    for p in ports:
        if is_large_port_range(p):
            return "error: port ranges larger than 5000 are not allowed in foreground scans"

    return script_scan_action(target,script,ports)

# HTTP for interacting with web endpoints
from prototype.mcp_stuff.http_actions import http_request_action
from typing import Any

@mcp.tool()
def http_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    cookies: Optional[Dict[str, str]] = None,
    raw_data: Optional[str] = None,
    json_data: Optional[Any] = None,
    form_data: Optional[Dict[str, str]] = None,
    files: Optional[Dict[str, str]] = None,
    follow_redirects: bool = True,
    verify_ssl: bool = True,
    timeout: int = 30,
    max_body_size: Optional[int] = 50_000,
    preset: str = "plain",
) -> Dict[str, Any]:
    """
    Execute an HTTP request with full method and body support.

    Args:
        method:           HTTP method — GET, POST, PUT, DELETE, HEAD,
                          OPTIONS, PATCH, PROPFIND, etc.
        url:              Full URL including scheme.
        headers:          Extra request headers (merged with preset).
        params:           URL query parameters dict.
        cookies:          Cookie dict.
        raw_data:         Raw request body string.
        json_data:        JSON body — sets Content-Type: application/json.
        form_data:        Form body — sets Content-Type: application/x-www-form-urlencoded.
        files:            Dictionary of field names to local file paths for file upload.
        follow_redirects: Follow 3xx redirects (default True).
        verify_ssl:       Verify SSL certificates (default True).
        timeout:          Seconds before giving up (default 30).
        max_body_size:    Max size of returned response body in bytes (default 50,000).
        preset:           Header preset — "plain" | "browser" | "api" | "webdav".

    Returns:
        dict with keys: status, reason, headers, body, cookies, content_type,
                        content_length, url, redirects, response_time,
                        body_truncated, encoding, error.
    """
    return http_request_action(
        method=method, url=url, headers=headers, params=params,
        cookies=cookies, raw_data=raw_data, json_data=json_data,
        form_data=form_data, files=files, follow_redirects=follow_redirects,
        verify_ssl=verify_ssl, timeout=timeout, max_body_size=max_body_size,
        preset=preset,
    )


#xss scanners [dalfox, xsstrike]
from prototype.mcp_stuff.dalfox_actions import dalfox_basic_scan_action
from prototype.mcp_stuff.xsstrike_actions import xsstrike_basic_scan_action

@mcp.tool()
def dalfox_basic_scan(target:str)->str:
    """
    Performs a basic XSS vulnerability scan on target using dalfox

    Args:
        target(str): The target url with/without any parameter eg., https://www.example.com or https://www.example.com?q=21

    Returns:
        str: The output of the scan
    """

    return dalfox_basic_scan_action(target=target)

@mcp.tool()
def xsstrike_basic_scan(target:str)->str:
    """
    Performs a basic XSS vulnerability scan on target using xsstrike

    Args:
        target(str): The target url with/without any parameter eg., https://www.example.com or https://www.example.com?q=21

    Returns:
        str: The output of the scan
    """

    return xsstrike_basic_scan_action(target=target)

#long running tasks specific function
from prototype.mcp_stuff.background_tasks import get_background_task_status, get_task_by_id, get_task_output

@mcp.tool()
def start_nmap_long_scan(
    target: str,
    ports: Union[str, List[str]] = None,
    max_runtime: int = 900
) -> Dict:
    """Start a long-running nmap scan in the background.

    Use this tool for scans that may take time, especially a complete TCP
    port sweep. There are 65,535 TCP ports. To scan every TCP port, pass
    ``ports="1-65535"``. Unlike the foreground nmap tools, this background
    path is intended for large ranges. If ``ports`` is omitted, the scan
    defaults to ``1-9000``; it does not scan all 65,535 ports automatically.
    Poll the returned task with ``get_task`` or retrieve output with
    ``get_task_output_mcp`` after waiting for the task to progress.

    Args:
        target (str): Target IP address or hostname. Only scan systems you
            are authorized to assess.
        ports (str | list[str], optional): Nmap port expression, such as
            ``"1-65535"`` for all TCP ports, ``"1-5000"`` for a range, or
            ``"22,80,443"`` for selected ports. Defaults to ``"1-9000"``.
        max_runtime (int): Maximum runtime in seconds before the task expires.

    """
    return start_nmap_long_scan_action(
        target=target,
        ports=ports,
        max_runtime=max_runtime,
    )

#feroxbuster
from prototype.mcp_stuff.feroxbuster_actions import (
    feroxbuster_foreground_action,
    start_feroxbuster_action,
)

@mcp.tool()
def foreground_feroxbuster(target: str) -> str:
    """Run a foreground feroxbuster scan with the bundled asset wordlist. intended to be used for Discovery L1"""
    return feroxbuster_foreground_action(target=target)

#TODO: add option for wordlists, names instead of path, point the wordlists name to its path using a dict
@mcp.tool()
def start_feroxbuster(
    target: str,
    max_runtime: int = 900
) -> Dict:
    """
    Start a long-running nmap scan in background.
    Returns task_id immediately.

    Args:
        target (str): The url of the webapp
    """
    return start_feroxbuster_action(target=target, max_runtime=max_runtime)

@mcp.tool()
def get_task_output_mcp(task_id: str) -> str:
    """
    Get output of a background task by ID.
    Returns empty string if not available yet.
    """
    output = get_task_output(task_id)
    return output or ""

@mcp.tool()
def get_task(task_id: str) -> Dict:
    """
    Get metadata for a specific background task by ID.
    """
    task = get_task_by_id(task_id)
    if not task:
        return {"error": "task not found"}
    return task


#due to the temporary fix, this function now also kills the expired tasks and marks them completed
@mcp.tool()
def get_all_bg_task_status() -> Dict:
    """
    Returns overview of pending+completed backgroud tasks
    """

    return get_background_task_status()


#python execution
from prototype.mcp_stuff.python_actions import execute_python

@mcp.tool()
def exe_cute_python(code:str, timeout:int=15):
    """
    Executes the python code and returns its output

    Args:
        code(str): The code to execute
        timeout(int): timeout for code execution, defaults to 15
    """

    return execute_python(code=code, timeout=timeout)

# Exploit Intel Tools
from prototype.mcp_stuff.exploit_intel_actions import (
    searchsploit_lookup,
)

@mcp.tool()
def searchsploit_search(technology: str) -> str:
    """
    Search the local ExploitDB via searchsploit for known exploits.

    Args:
        technology: Technology or CVE ID to search e.g. "copyparty", "CVE-2023-1234"

    Returns:
        str: Exploit titles, IDs, and file paths from ExploitDB
    """
    return searchsploit_lookup(technology)


if __name__=="__main__":
    print("mcp server started")
    try:
        mcp.run(transport="streamable-http")
    except KeyboardInterrupt:
        print("\nShutting down MCP server cleanly...")
