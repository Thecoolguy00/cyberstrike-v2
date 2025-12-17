import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph, MessagesState, START
from langchain_core.messages import HumanMessage,SystemMessage


class State(MessagesState):
    pass


# LLM
model = ChatOpenAI(
    model="qwen-local",
    openai_api_base="http://127.0.0.1:8080/v1",
    openai_api_key="none",
    temperature=0.2,
)

# MCP client (async init)
client = MultiServerMCPClient(
    {
        "nmap_tools": {
            "url": "http://localhost:4545/mcp",
            "transport": "streamable_http",
        }
    }
)

async def init_graph():
    tools = await client.get_tools()

    sys_prompt="you are a nmap expert, use the tools provided to execute nmap"
    def call_model(state: State):
        response = model.bind_tools(tools).invoke([SystemMessage(content=sys_prompt)]+state["messages"])
        return {"messages": response}

    builder = StateGraph(MessagesState)
    builder.add_node("call_model", call_model)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", tools_condition)
    builder.add_edge("tools", "call_model")

    return builder.compile()


# Export graph for LangGraph runtime (important!)
graph = asyncio.run(init_graph())


# Optional: Run manually
# if __name__ == "__main__":
#     result = graph.invoke({"messages": [HumanMessage(content="perform a basic nmap scan on 127.0.0.1")]})
#     print(result["messages"][-1].content)
