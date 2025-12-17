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
from sub_agents.util import extract_tool_Schema, format_history, response_route
from sub_agents.prompt_template import get_agent_prompt
from sub_agents.true_mcp_exec import get_mcp_tools
load_dotenv()

api_key_3=os.getenv("GEMINI_API_KEY_3","")
model=ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key_3)

class CurlState(MessagesState):
    tool_used:Annotated[List[str],operator.add]

tool_list=asyncio.run(get_mcp_tools())
curl_tool_names = [
    "get_header",
    "get_page"
]
curl_tool_list=[t for t in tool_list if t.name in curl_tool_names]

tool_schema=extract_tool_Schema(curl_tool_list)
agent_prompt="You are a expert curl agent, answer the users query using available tools"


def curl_agent(state:CurlState):
    history=format_history(state["messages"])
    prompt=get_agent_prompt(
        tool_schema=tool_schema,
        history=history,
        agent_prompt=agent_prompt,
        state=state)
    
    response=model.invoke(prompt)
    return response_route(response)

flow=StateGraph(CurlState)

flow.add_node("curl_agent",curl_agent)
flow.add_node("tools", ToolNode(curl_tool_list))

flow.add_edge(START,"curl_agent")
flow.add_conditional_edges("curl_agent",tools_condition)
flow.add_edge("tools", "curl_agent")

graph=flow.compile()