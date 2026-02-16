import asyncio
import json
import operator
from typing import TypedDict, List, Optional, Annotated
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph,START, END, MessagesState
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.output_parsers import PydanticOutputParser

from prototype.sub_agents.helper import extract_tool_Schema, format_history, response_route, tool_schema_from_func, mcp_exec_node, tool_router
from prototype.sub_agents.true_mcp_exec import get_mcp_tools
from prototype.sub_agents.search_actions import search_tavily
from prototype.sub_agents.schema_validator import invoke_and_validate
from prototype.sub_agents.prompt import get_agent_system_message, get_agent_user_message
from prototype.sub_agents.schema import BaseState

from app.utilities.llm_helper import LLMHelper

groq_llm = LLMHelper.get_llm_for_service("nmap_a")

class NmapState(BaseState):
    pass

tool_list=asyncio.run(get_mcp_tools())

#too much abstraction makes you forget primitives

#these are mcp tool that are not executable with our custom langgraph tool pipline so we made a custom mcp node for it
nmap_tool_names = [
    "basic_scan",
    "aggressive_scan",
    "noping_version_scan",
    "script_scan",
    "start_nmap_long_scan",
    "get_task_output_mcp"
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
    
    #graph, maybe modularise this
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