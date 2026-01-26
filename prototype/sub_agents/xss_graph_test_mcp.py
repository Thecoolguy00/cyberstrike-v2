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
from prototype.sub_agents.s0 import invoke_and_validate
from prototype.sub_agents.p0 import get_agent_system_message, get_agent_user_message
from prototype.sub_agents.schema import BaseState

from app.utilities.llm_helper import LLMHelper

groq_llm = LLMHelper.get_llm_for_service("xss_a")

class XssState(BaseState):
    pass

tool_list=asyncio.run(get_mcp_tools())

#these are mcp tool that are not executable with our custom pipline so we use our custom mcp node for it
xss_tool_names = [
    "dalfox_basic_scan",
    "xsstrike_basic_scan"
]
xss_tool_list=[t for t in tool_list if t.name in xss_tool_names]

mcp_tool_schema=extract_tool_Schema(xss_tool_list)
normal_tool_schema=tool_schema_from_func([search_tavily])

tool_schema=mcp_tool_schema+normal_tool_schema

agent_prompt="You are a expert xss agent, answer the users query using available tools"

async def init_graph():

    #groq
    async def agent_node(state: XssState):
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
            SystemMessage(content=get_agent_system_message(agent_type="xss",tool_schema=tool_schema)),
            HumanMessage(content=prompt)
        ]

        response=invoke_and_validate(llm=groq_llm, messages=messages)
        messages=messages+[response]

        return await response_route(response)

    #graph
    flow=StateGraph(XssState)

    flow.add_node("mcp_exec",mcp_exec_node)
    flow.add_node("xss_agent",agent_node)
    flow.add_node("tools",ToolNode([search_tavily]))

    flow.add_edge(START,"xss_agent")
    flow.add_conditional_edges(
        "xss_agent",
        tool_router,
        {
            "mcp_exec": "mcp_exec",
            "tools": "tools",
            END: END
        }
    )
    flow.add_edge("tools","xss_agent")
    flow.add_edge("mcp_exec","xss_agent")
    graph=flow.compile()

    return graph

graph=asyncio.run(init_graph())


if __name__ == "__main__":
    result = asyncio.run(
        graph.ainvoke({
            "messages": [HumanMessage(content="scan http://example.com/ for XSS")],
            "tool_used": []
        })
    )
    print(result)


#currently the most stable and working agent