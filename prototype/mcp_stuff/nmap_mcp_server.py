from mcp.server.fastmcp import FastMCP
from typing import Optional
from prototype.mcp_stuff.nmap_actions import basic_scan_action,script_scan_action,intense_scan_action,no_ping_scan_action,recommended_scan_action

mcp = FastMCP(name="nmap-tools",host="0.0.0.0",port=4545)

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
def intense_scan(target: str, ports: Optional[list[str]] = None) -> str:
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
def no_ping_scan(target: str, ports: Optional[list[str]] = None) -> str:
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
def recommended_scan(target: str, ports: Optional[list[str]] = None) -> str:
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
def script_scan(target: str, script: str, ports: list[str]) -> str:
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

if __name__ == "__main__":
    print("mcp server started")
    mcp.run(transport="streamable-http")