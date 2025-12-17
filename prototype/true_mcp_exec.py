import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from httpx import HTTPStatusError
from dotenv import load_dotenv
import os

load_dotenv()

async def run_mcp_tool(tool_name: str, args: dict):
    """
    Connect to an MCP server over Streamable HTTP, list tools, call one, return result string.
    """
    mcp_url=os.getenv("MCP_BASE_URL","http://192.168.26.128:4545/mcp")
    # Ensure URL does not accidentally double slash
    mcp_url = mcp_url.rstrip("/")

    async with streamablehttp_client(mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            info = await session.list_tools()
            tool_names = [t.name for t in info.tools]
            print("Available tools:", tool_names)

            if tool_name not in tool_names:
                raise ValueError(f"Tool {tool_name} not found among {tool_names}")

            result = await session.call_tool(tool_name, args)

            # result.content is list of dicts with 'text'/'data'
            output = []
            for item in result.content:
                if hasattr(item, "text"):
                    output.append(item.text)
                else:
                    output.append(str(item))


    return "\n".join(output)


async def get_mcp_tools():
    """
    Lists available mcp tools
    """
    mcp_url=os.getenv("MCP_BASE_URL","http://192.168.26.128:4545/mcp")
    # Ensure URL does not accidentally double slash
    mcp_url = mcp_url.rstrip("/")

    async with streamablehttp_client(mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()

    return result.tools
    


if __name__ == "__main__":
    tool = "basic_scan"
    arguments = {"target": "127.0.0.1"}

    try:
        result = asyncio.run(run_mcp_tool(tool, arguments))
        print("Tool output:\n", result)
    except HTTPStatusError as err:
        print("HTTP error from server:", err.response.status_code, err.response.text)
    except Exception as exc:
        print("Error:", type(exc).__name__, exc)

    # print(asyncio.run(get_mcp_tools()))
