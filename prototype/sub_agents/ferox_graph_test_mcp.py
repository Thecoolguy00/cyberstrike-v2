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

from prototype.sub_agents.helper import extract_tool_Schema, format_history, response_route, tool_schema_from_func, mcp_exec_node, tool_router
from prototype.sub_agents.p0 import get_agent_system_message, get_agent_user_message
from prototype.sub_agents.true_mcp_exec import get_mcp_tools
from prototype.sub_agents.search_actions import search_tavily
from prototype.sub_agents.s0 import invoke_and_validate
load_dotenv()

groq_key=os.getenv("GROQ_API_KEY","")

groq_llm = ChatGroq(
    model="moonshotai/kimi-k2-instruct-0905",
    api_key=groq_key,
    temperature=0.6
)

class FeroxState(MessagesState):
    tool_used:Annotated[List[str],operator.add]
    task:str
    
tool_list=asyncio.run(get_mcp_tools())

#these are mcp tool that are not executable with our custom pipline so we use our custom mcp node for it
ferox_tool_names = [
    "start_feroxbuster",
    "get_task_output_mcp"
    ]
ferox_tool_list=[t for t in tool_list if t.name in ferox_tool_names]

mcp_tool_schema=extract_tool_Schema(ferox_tool_list)
normal_tool_schema=tool_schema_from_func([search_tavily])

tool_schema=mcp_tool_schema+normal_tool_schema

agent_prompt="You are a expert ferox agent, answer the users query using available tools"

async def init_graph():

    #groq
    async def agent_node(state: FeroxState):
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
            SystemMessage(content=get_agent_system_message(agent_type="feroxbuster",tool_schema=tool_schema)),
            HumanMessage(content=prompt)
        ]

        response=invoke_and_validate(llm=groq_llm, messages=messages)
        messages=messages+[response]

        return await response_route(response)

    #graph
    flow=StateGraph(FeroxState)

    flow.add_node("mcp_exec",mcp_exec_node)
    flow.add_node("ferox_agent",agent_node)
    flow.add_node("tools",ToolNode([search_tavily]))

    flow.add_edge(START,"ferox_agent")
    flow.add_conditional_edges(
        "ferox_agent",
        tool_router,
        {
            "mcp_exec": "mcp_exec",
            "tools": "tools",
            END: END
        }
    )
    flow.add_edge("tools","ferox_agent")
    flow.add_edge("mcp_exec","ferox_agent")
    graph=flow.compile()

    return graph

graph=asyncio.run(init_graph())


if __name__ == "__main__":
    result = asyncio.run(
        graph.ainvoke({
            "messages": [HumanMessage(content="run ferox on 127.0.0.1 and then search for 'elden ring' ")],
            "tool_used": []
        })
    )
    print(result)


#currently the most stable and working agent