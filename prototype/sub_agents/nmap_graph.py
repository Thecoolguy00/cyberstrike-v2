import asyncio
from dotenv import load_dotenv
import os
import json
import operator
from pydantic import BaseModel
from typing import TypedDict, List, Optional, Annotated
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph,START, END, MessagesState
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_mcp_adapters.client import MultiServerMCPClient
from sub_agents.util import extract_tool_Schema, format_history, response_route, wrap_mcp_tools
from sub_agents.prompt_template import get_agent_prompt
from sub_agents.true_mcp_exec import get_mcp_tools
load_dotenv()

api_key_2=os.getenv("GEMINI_API_KEY_2","")
model=ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key_2,streaming=False)

class NmapState(MessagesState):
    tool_used:Annotated[List[str],operator.add]

tool_list=asyncio.run(get_mcp_tools())
nmap_tool_names = [
    "basic_scan",
    "intense_scan",
    "recommended_scan",
    "no_ping_scan",
    "script_scan"
]
nmap_tool_list=[t for t in tool_list if t.name in nmap_tool_names]

tool_schema=extract_tool_Schema(nmap_tool_list)
agent_prompt="You are a expert nmap agent, answer the users query using available tools"


def nmap_agent(state:NmapState):
    history=format_history(state["messages"])
    prompt=get_agent_prompt(
        tool_schema=tool_schema,
        history=history,
        agent_prompt=agent_prompt,
        state=state)
    
    response=model.invoke(prompt)
    return response_route(response)

flow=StateGraph(NmapState)

flow.add_node("nmap_agent",nmap_agent)
flow.add_node("tools", ToolNode(nmap_tool_list))

flow.add_edge(START,"nmap_agent")
flow.add_conditional_edges("nmap_agent",tools_condition)
flow.add_edge("tools", "nmap_agent")

graph=flow.compile()