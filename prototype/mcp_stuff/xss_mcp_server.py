from mcp.server.fastmcp import FastMCP
from prototype.mcp_stuff.dalfox_actions import dalfox_basic_scan_action
from prototype.mcp_stuff.xsstrike_actions import xsstrike_basic_scan_action

mcp=FastMCP(name="xss-tools",host="0.0.0.0",port=4550)

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

if __name__=="__main__":
    print("mcp server started")
    mcp.run(transport="streamable-http") 