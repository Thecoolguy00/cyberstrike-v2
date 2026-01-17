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
    import json
    import time

    # Example: Start a long-running nmap scan
    tool = "start_nmap_long_scan"
    arguments = {"target": "127.0.0.1", "ports": ["80", "443"]}

    try:
        # Start the task
        result = asyncio.run(run_mcp_tool(tool, arguments))
        print("Start result:", result)

        # Parse the JSON response to get task_id
        start_result = json.loads(result)
        task_id = start_result.get("task_id")
        if not task_id:
            print("Failed to get task_id")

        print(f"Task started with ID: {task_id}")

        # Wait a bit for the task to run (adjust time as needed)
        print("Waiting 10 seconds for task to complete...")
        time.sleep(10)

        # Get the task output
        output_tool = "get_task_output_mcp"
        output_args = {"task_id": task_id}
        output = asyncio.run(run_mcp_tool(output_tool, output_args))
        print("Task output:\n", output)

        # Alternatively, check task status
        status_tool = "get_task"
        status_args = {"task_id": task_id}
        status = asyncio.run(run_mcp_tool(status_tool, status_args))
        print("Task status:", status)

    except json.JSONDecodeError:
        print("Failed to parse start result as JSON")
    except HTTPStatusError as err:
        print("HTTP error from server:", err.response.status_code, err.response.text)
    except Exception as exc:
        print("Error:", type(exc).__name__, exc)