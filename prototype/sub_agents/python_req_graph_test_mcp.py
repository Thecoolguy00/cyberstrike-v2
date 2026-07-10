import asyncio
import json
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph,START, END, MessagesState
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.output_parsers import PydanticOutputParser

from prototype.sub_agents.helper import extract_tool_Schema, format_history, response_route, tool_schema_from_func, mcp_exec_node, tool_router
from prototype.sub_agents.true_mcp_exec import get_mcp_tools
from prototype.sub_agents.search_actions import search_tavily
from prototype.sub_agents.schema_validator import invoke_and_validate
from prototype.sub_agents.prompt import get_agent_system_message, get_agent_user_message
from prototype.sub_agents.schemas import BaseState

from app.utilities.llm_helper import LLMHelper

groq_llm = LLMHelper.get_llm_for_service("python_req_a")

class NmapState(BaseState):
    pass

tool_list=asyncio.run(get_mcp_tools())

#these are mcp tool that are not executable with our custom langgraph tool pipline so we made a custom mcp node for it
python_tool_names = [
    "exe_cute_python"
]
python_tool_list=[t for t in tool_list if t.name in python_tool_names]

mcp_tool_schema=extract_tool_Schema(python_tool_list)
normal_tool_schema=tool_schema_from_func([search_tavily])

tool_schema=mcp_tool_schema+normal_tool_schema

#just seeing that im not using it anywhere, TODO remove it later from every agent
agent_prompt="You are a expert python executor agent, answer the users query using available tools"

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
            SystemMessage(content=get_agent_system_message(agent_type="python_executor",tool_schema=tool_schema)),
            HumanMessage(content=prompt)
        ]

        response=invoke_and_validate(llm=groq_llm, messages=messages)
        messages=messages+[response]

        return await response_route(response)
    
    #graph
    flow=StateGraph(NmapState)

    flow.add_node("mcp_exec",mcp_exec_node)
    flow.add_node("python_agent",agent_node)
    flow.add_node("tools",ToolNode([search_tavily]))

    flow.add_edge(START,"python_agent")
    flow.add_conditional_edges(
        "python_agent",
        tool_router,
        {
            "mcp_exec": "mcp_exec",
            "tools": "tools",
            END: END
        }
    )
    flow.add_edge("tools","python_agent")
    flow.add_edge("mcp_exec","python_agent")
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