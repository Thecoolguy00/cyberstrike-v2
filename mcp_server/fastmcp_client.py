import asyncio
from fastmcp import Client

#fastmcp has no direct integration with langchain

async def main():
    client = Client("http://localhost:4545/mcp")
    async with client:
        #lists tool
        tools = await client.list_tools()        
        for tool in tools:
            print(f"Tool: {tool.name}")
            print(f"Description: {tool.description}")
            if getattr(tool, "inputSchema", None):
                print("Parameters:")
                print(tool.inputSchema)
            if hasattr(tool, "meta") and tool.meta:
                fastmcp_meta = tool.meta.get("_fastmcp", {})
                print("Tags:", fastmcp_meta.get("tags", []))
            print("-" * 40)

        #example tool call
        result = await client.call_tool("recommended_scan", {"target": "127.0.0.1","ports":[445]})
        if hasattr(result, "data") and result.data:
            print(result.data)
        elif result.structured_content and "result" in result.structured_content:
            print(result.structured_content["result"])
        elif result.content:
            for c in result.content:
                if hasattr(c, "text"):
                    print(c.text)
        else:
            print("No output received.")

if __name__ == "__main__":
    asyncio.run(main())
