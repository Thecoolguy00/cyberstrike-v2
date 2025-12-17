from mcp.server.fastmcp import FastMCP
from feroxbuster_actions import run_feroxbuster

mcp=FastMCP(name="combined_tools",host="0.0.0.0",port=4545)

#feroxbuster for directory brute forcing
@mcp.tool()
async def execute_feroxbuster(url:str,
                        wordlist: str="/usr/share/wordlists/dirb/common.txt",
                        runtime:int=120,
                        idle_time:int=15,
                        poll_interval:int=2
                        )->str:
    """
    Launch feroxbuster in background, wait 'runtime' seconds,
    then fetch and return results.

    Args:
        url(str): The url of the webapp.
        wordlist(str): path to the wordlist,defaults to /usr/share/wordlists/dirb/common.txt (optional)
        runtime(int): the max runtime in seconds to be allowed,defaults to 120s (optional)
        idle_time(int): the max time for the output file to be idle before termination,defaults to 15s (optional)
        poll_interval(int):the interval for output polling for status checking, detaults to 2s (optional)

    Returns:
        str: The output of feroxbuster after termination
    """   
    return await run_feroxbuster(url,wordlist,runtime,idle_time,poll_interval)

#nmap for network scan
from typing import Optional
from nmap_actions import basic_scan_action,script_scan_action,intense_scan_action,no_ping_scan_action,recommended_scan_action

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
def intense_scan(target: str, ports: Optional[list[int]] = None) -> str:
    """Perform an intense network scan using nmap.

    Args:
        target (str): The target IP address or hostname to scan.
        ports (list): The list of ports to scan (optional)

    Returns:
        str: The output results of the intense scan.
    """
    ports = ports or []
    return intense_scan_action(target,ports)

@mcp.tool()
def no_ping_scan(target: str, ports: Optional[list[int]] = None) -> str:
    """Perform an no-ping scan using nmap.

    Args:
        target (str): The target IP address or hostname to scan.
        ports (list): The list of ports to scan (optional)

    Returns:
        str: The output results of the no ping scan.
    """
    ports = ports or []
    return no_ping_scan_action(target,ports)

@mcp.tool()
def recommended_scan(target: str, ports: Optional[list[int]] = None) -> str:
    """Perform an network scan with recommended parameters using nmap.

    Args:
        target (str): The target IP address or hostname to scan.
        ports (list): The list of ports to scan (optional)

    Returns:
        str: The output results of the recommended scan.
    """
    ports = ports or []
    return recommended_scan_action(target,ports)

@mcp.tool()
def script_scan(target: str, script: str, ports: list[int]) -> str:
    """Perform an script scan on specified port and target using nmap

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
from curl_actions import get_headers_action,get_page_content

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
def get_page(url:str)->str:
    """Return full page content (curl -sL)

    Args:
        url(str): the target url eg.,https://www.example.org/

    Returns:
        str: The page content of the HTTP response
    """
    return get_page_content(url)

if __name__=="__main__":
    print("mcp server started")
    mcp.run(transport="streamable-http") 