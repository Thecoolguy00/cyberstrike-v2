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
from langchain_groq import ChatGroq

from util import extract_tool_Schema, format_history, response_route, tool_schema_from_func, mcp_exec_node, tool_router
from true_mcp_exec import get_mcp_tools
from search_actions import search_tavily
from s0 import invoke_and_validate
from p0 import get_agent_system_message, get_agent_user_message
load_dotenv()

groq_key=os.getenv("GROQ_API_KEY","")

groq_llm = ChatGroq(
    model="moonshotai/kimi-k2-instruct-0905",
    api_key=groq_key,
    temperature=0.6
)

class NmapState(MessagesState):
    tool_used:Annotated[List[str],operator.add]
    task:str

tool_list=asyncio.run(get_mcp_tools())

#these are mcp tool that are not executable with our custom langgraph tool pipline so we made a custom mcp node for it
nmap_tool_names = [
    "basic_scan",
    "aggressive_scan",
    "noping_version_scan",
    "script_scan"
]
nmap_tool_list=[t for t in tool_list if t.name in nmap_tool_names]

mcp_tool_schema=extract_tool_Schema(nmap_tool_list)
normal_tool_schema=tool_schema_from_func([search_tavily])

tool_schema=mcp_tool_schema+normal_tool_schema

agent_prompt="You are a expert nmap agent, answer the users query using available tools"

async def init_graph():

    #groq
    async def agent_node(state: NmapState):
        """
        Agent node using Groq LLM backend
        """
        history=format_history(state["messages"])
        task=state["task"]
        prompt=get_agent_user_message(
            task=task,
            history=history,
            state=state)
        
        messages = [
            SystemMessage(content=get_agent_system_message(agent_type="nmap",tool_schema=tool_schema)),
            HumanMessage(content=prompt)
        ]

        response=invoke_and_validate(llm=groq_llm, messages=messages)
        messages=messages+[response]

        return await response_route(response)
    
    #graph
    flow=StateGraph(NmapState)

    flow.add_node("mcp_exec",mcp_exec_node)
    flow.add_node("nmap_agent",agent_node)
    flow.add_node("tools",ToolNode([search_tavily]))

    flow.add_edge(START,"nmap_agent")
    flow.add_conditional_edges(
        "nmap_agent",
        tool_router,
        {
            "mcp_exec": "mcp_exec",
            "tools": "tools",
            END: END
        }
    )
    flow.add_edge("tools","nmap_agent")
    flow.add_edge("mcp_exec","nmap_agent")
    graph=flow.compile()

    return graph

graph=asyncio.run(init_graph())


if __name__ == "__main__":
    result = asyncio.run(
        graph.ainvoke({
            "messages": [HumanMessage(content="scan 127.0.0.1 and then search for 'elden ring' ")],
            "tool_used": []
        })
    )
    data=result["messages"][-1].content
    loaded=json.loads(data)
    print(loaded["message"])


#currently the most stable and working agent