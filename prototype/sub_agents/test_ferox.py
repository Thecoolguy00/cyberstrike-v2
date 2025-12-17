import asyncio
from dotenv import load_dotenv
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph, MessagesState, START
from langchain_core.messages import SystemMessage

load_dotenv()

class State(MessagesState):
    pass

async def init_graph():
    api_key = os.getenv("GEMINI_API_KEY_2", "")
    model = ChatGoogleGenerativeAI(model="gemini-2.0-flash", api_key=api_key)

    client = MultiServerMCPClient({
        "combined_tools": {
            "url": "http://192.168.26.128:4545/mcp",
            "transport": "streamable_http",
        }
    })

    tools = await client.get_tools()
    ferox = [t for t in tools if t.name == "execute_feroxbuster"]

    sys_prompt = (
        "You are a feroxbuster expert. "
        "Use the available 'execute_feroxbuster' tool to perform directory brute-forcing and answer user query."
    )

    def call_model(state: State):
        messages = [SystemMessage(content=sys_prompt)] + state["messages"]
        response = model.bind_tools(ferox).invoke(messages)
        return {"messages": response}

    builder = StateGraph(State)
    builder.add_node("call_model", call_model)
    builder.add_node("tools", ToolNode(ferox))

    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", tools_condition)
    builder.add_edge("tools", "call_model")

    return builder.compile()

graph = asyncio.run(init_graph())
