from mcp.server.fastmcp import FastMCP
from prototype.mcp_stuff.feroxbuster_actions import run_feroxbuster
from typing import Dict, List, Sequence, Union
from pathlib import Path

mcp=FastMCP(name="combined_tools",host="0.0.0.0",port=4545)

#feroxbuster for directory brute forcing
# @mcp.tool()
# async def execute_feroxbuster(url:str,
#                         wordlist: str="/usr/share/wordlists/dirb/common.txt",
#                         runtime:int=120,
#                         idle_time:int=15,
#                         poll_interval:int=2
#                         )->str:
#     """
#     Launch feroxbuster in background, wait 'runtime' seconds,
#     then fetch and return results.

#     Args:
#         url(str): The url of the webapp.
#         wordlist(str): path to the wordlist,defaults to /usr/share/wordlists/dirb/common.txt (optional)
#         runtime(int): the max runtime in seconds to be allowed,defaults to 120s (optional)
#         idle_time(int): the max time for the output file to be idle before termination,defaults to 15s (optional)
#         poll_interval(int):the interval for output polling for status checking, detaults to 2s (optional)

#     Returns:
#         str: The output of feroxbuster after termination
#     """   
#     return await run_feroxbuster(url,wordlist,runtime,idle_time,poll_interval)

#nmap for network scan
from typing import Optional
from prototype.mcp_stuff.nmap_actions import basic_scan_action,script_scan_action,aggressive_scan_action,noping_version_scan_action

#helper fucntion for normalising ports

def port_args(ports: Optional[Sequence[Union[int, str]]]) -> List[str]:
    """Return ['-p', '22,80'] if ports present, else []"""
    if not ports:
        return []
    return ["-p", ",".join(map(str, ports))]

@mcp.tool()
def basic_scan(target: str) ->str:
    """Perform a basic network scan using nmap.

    Args:
        target (str): The target IP address or hostname to scan.

    Returns:
        str: The output results of the basic scan.
    """
    return basic_scan_action(target)

@mcp.tool()
def aggressive_scan(target: str, ports: Optional[list[str]] = None) -> str:
    """Perform an nmap aggressive network scan using -A parameter(includes OS detection, version detection, default script scanning, and traceroute)

    Args:
        target (str): The target IP address or hostname to scan.
        ports (list): The list of ports to scan (optional)

    Returns:
        str: The output results of the intense scan.
    """
    ports = ports or []
    return aggressive_scan_action(target,ports)

@mcp.tool()
def noping_version_scan(target: str, ports: Optional[list[str]] = None) -> str:
    """Perform an nmap service scan with ping diabled, this is the recommened scan w/wo ports.

    Args:
        target (str): The target IP address or hostname to scan.
        ports (list): The list of ports to scan (optional)

    Returns:
        str: The output results of the recommended scan.
    """
    ports = ports or []
    return noping_version_scan_action(target,ports)

@mcp.tool()
def script_scan(target: str, script: str, ports: list[str]) -> str:
    """Perform an nmap script scan on specified port and target

    Args:
        target (str): The target IP address or hostname to scan.
        script (str): The specific nmap script
        ports (list): The list of ports to scan

    Returns:
        str: The output results of the script scan.
    """
    ports = ports or []
    return script_scan_action(target,script,ports)

#curl for getting headers and page content
from prototype.mcp_stuff.curl_actions import get_headers_action,get_full_page_action, get_partial_page_action

@mcp.tool()
def get_header(url:str)->str:
    """Return HTTP headers (curl -I)

    Args:
        url(str): the target url eg.,https://www.example.org/

    Returns:
        str: The header of the HTTP response
    """
    return get_headers_action(url)

@mcp.tool()
def get_full_page(url:str)->str:
    """Return full page content (curl -sL)

    Args:
        url(str): the target url eg.,https://www.example.org/

    Returns:
        str: The page content of the HTTP response
    """
    return get_full_page_action(url)

@mcp.tool()
def get_partial_page(url:str, size_limit:int=2000)->str:
    """
    Returns the partial page content upto the sizelimit, defaults to 2000

    Args
        url(str): the target url eg.,https://www.example.org/
        size_limit(int): the size limit of the returned page, defaults to 2000 (Optional)

    Returns:
        str: The partial content of the HTTP response depending upon the size_limit
    """

    return get_partial_page_action(url=url,size_limit=size_limit)


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
from prototype.mcp_stuff.background_tasks import launch_background_task, get_background_task_status, get_task_by_id, get_task_output

@mcp.tool()
def start_nmap_long_scan(
    target: str,
    ports: List[str],
    max_runtime: int = 900
) -> Dict:
    """
    Start a long-running nmap scan in background.

    Args:
        target (str): The target IP address or hostname to scan.
        ports (list): The list of ports to scan (optional)
    """
    task_id, output_file = launch_background_task(
        cmd="nmap",
        args=port_args(ports=ports) + [target],
        max_runtime=max_runtime
    )

    return {
        "task_id": task_id,
        "status": "started",
        "output_file": str(output_file),
        "max_runtime": max_runtime
    }


@mcp.tool()
def start_feroxbuster(
    target: str,
    max_runtime: int = 900
) -> Dict:
    """
    Start a long-running nmap scan in background.
    Returns task_id immediately.
    """
    wordlist = "/usr/share/wordlists/dirb/common.txt"

    if not Path(wordlist).exists():
        return {
            "error": "wordlist not found",
            "status": "failed"
        }
    
    # Basic feroxbuster args
    args = ["-u", target, "-w", wordlist]

    task_id, output_file = launch_background_task(cmd="feroxbuster", args=args, max_runtime=max_runtime)

    return {
        "task_id": task_id,
        "status": "started",
        "output_file": str(output_file),
        "max_runtime": max_runtime
    }

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

@mcp.tool()
def get_all_bg_task_status() -> Dict:
    """
    Returns overview of pending+completed backgroud tasks
    """

    return get_background_task_status()


if __name__=="__main__":
    print("mcp server started")
    try:
        mcp.run(transport="streamable-http")
    except KeyboardInterrupt:
        print("Shutting down MCP server...") 
