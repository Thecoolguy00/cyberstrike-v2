from mcp.server.fastmcp import FastMCP
from feroxbuster_actions import run_feroxbuster

mcp=FastMCP(name="feroxbuster",host="0.0.0.0",port=4555)

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


if __name__=="__main__":
    print("mcp server started")
    mcp.run(transport="streamable-http") 