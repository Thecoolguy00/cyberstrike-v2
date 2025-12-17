import asyncio
from dotenv import load_dotenv
import os
from pydantic import BaseModel
from typing import TypedDict, List
from search_actions import search_tavily, search_wikipedia
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph, MessagesState, START, END
from langchain_core.messages import SystemMessage, HumanMessage
from langchain.tools import StructuredTool

load_dotenv()

api_key_1=os.getenv("GEMINI_API_KEY_1","")
model=ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key_1)

class PlanState(TypedDict):
    query:str
    tasks:List[str]

# MCP client (async init)
client = MultiServerMCPClient(
    {
        "combined_tools": {
            "url": "http://192.168.26.128:4545/mcp",
            "transport": "streamable_http",
        }
    }
)

async def get_mcp_tools():
    tools = await client.get_tools()
    return tools
tool_list=asyncio.run(get_mcp_tools())



search_wikipedia_tool = StructuredTool.from_function(search_wikipedia)
search_tavily_tool = StructuredTool.from_function(search_tavily)

def plan_agent(state:PlanState):
    query=state.get("query","")
    tools=tool_list+[search_wikipedia_tool, search_tavily_tool]
    prompt=f"""
    You are a expert planner,\n
    use the provided tools to create a json structured plan according to the given structure to complete the current query:{query}
    JSON Structure:
    plan:list[dict[name,args]]
    
    note:
    -Only choose the minimal number of tools necessary to satisfy the query.
    -Do NOT run multiple tools that perform the same function.
    -Choose the single best tool for the task.
    """

    response=model.bind_tools(tools).invoke([HumanMessage(content=prompt)])

    return {"tasks":response}


flow=StateGraph(PlanState)
flow.add_node("planner",plan_agent)
flow.add_edge(START,"planner")
flow.add_edge("planner",END)

graph=flow.compile()

print(tool_list+[search_wikipedia_tool, search_tavily_tool])