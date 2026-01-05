from mcp.server.fastmcp import FastMCP
from prototype.mcp_stuff.curl_actions import get_headers_action,get_full_page_action, get_partial_page_action

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

if __name__=="__main__":
    print("mcp server started")
    mcp.run(transport="streamable-http") 