import asyncio
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

from prototype.sub_agents.helper import (
    extract_tool_Schema, format_history, response_route,
    tool_schema_from_func, mcp_exec_node, tool_router,
)
from prototype.sub_agents.true_mcp_exec import get_mcp_tools
from prototype.sub_agents.search_actions import search_tavily
from prototype.sub_agents.schema_validator import invoke_and_validate
from prototype.sub_agents.prompt import get_agent_system_message, get_agent_user_message
from prototype.sub_agents.schemas import BaseState
from app.utilities.llm_helper import LLMHelper

http_llm = LLMHelper.get_llm_for_service("http_a")

class HttpState(BaseState):
    pass

tool_list = asyncio.run(get_mcp_tools())

http_tool_names = ["http_request"]
http_tool_list = [t for t in tool_list if t.name in http_tool_names]

mcp_tool_schema  = extract_tool_Schema(http_tool_list)
normal_tool_schema = tool_schema_from_func([search_tavily])
tool_schema = mcp_tool_schema + normal_tool_schema

async def init_graph():
    async def agent_node(state: HttpState):
        history = format_history(state["messages"])
        task    = state["task"]
        prompt  = get_agent_user_message(task=task, history=history, state=state)

        messages = [
            SystemMessage(content=get_agent_system_message(
                agent_type="http",
                tool_schema=tool_schema,
            )),
            HumanMessage(content=prompt),
        ]

        response = invoke_and_validate(llm=http_llm, messages=messages)
        return response_route(response)

    flow = StateGraph(HttpState)
    flow.add_node("mcp_exec",   mcp_exec_node)
    flow.add_node("http_agent", agent_node)
    flow.add_node("tools",      ToolNode([search_tavily]))

    flow.add_edge(START, "http_agent")
    flow.add_conditional_edges(
        "http_agent",
        tool_router,
        {"mcp_exec": "mcp_exec", "tools": "tools", END: END},
    )
    flow.add_edge("tools",    "http_agent")
    flow.add_edge("mcp_exec", "http_agent")

    return flow.compile().with_config({"run_name": "HTTP Inspection Graph"})

graph = asyncio.run(init_graph())
