from mcp.server.fastmcp import FastMCP
from prototype.mcp_stuff.curl_actions import get_headers_action,get_page_content

mcp=FastMCP(name="curl-tools",host="0.0.0.0",port=4550)

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