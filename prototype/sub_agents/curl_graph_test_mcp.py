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
from prompt_template import get_agent_prompt
from true_mcp_exec import get_mcp_tools
from search_actions import search_tavily
load_dotenv()

api_key_2=os.getenv("GEMINI_API_KEY_3","")

model = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    api_key=api_key_2,
    streaming=False,
    max_retries=0
)
groq_key=os.getenv("GROQ_API_KEY","")

groq_llm = ChatGroq(
    model="moonshotai/kimi-k2-instruct-0905",
    api_key=groq_key,
    temperature=0.5
)

class CurlState(MessagesState):
    tool_used:Annotated[List[str],operator.add]

tool_list=asyncio.run(get_mcp_tools())

#these are mcp tool that are not executable with our custom pipline so we use our custom mcp node for it
curl_tool_names = [
    "get_header",
    "get_page"
]
curl_tool_list=[t for t in tool_list if t.name in curl_tool_names]

mcp_tool_schema=extract_tool_Schema(curl_tool_list)
normal_tool_schema=tool_schema_from_func([search_tavily])

tool_schema=mcp_tool_schema+normal_tool_schema

agent_prompt="You are a expert curl agent, answer the users query using available tools"

async def init_graph():

    #groq
    async def agent_node(state: CurlState):
        """
        Agent node using Groq LLM backend
        """
        history=format_history(state["messages"])
        prompt=get_agent_prompt(
            tool_schema=tool_schema,
            history=history,
            agent_prompt=agent_prompt,
            state=state)
        
        messages = [
            ("human", prompt)
        ]

        # call Groq LLM using tuple message format
        response = groq_llm.invoke(messages)
        messages=messages+[response]

        return await response_route(response)
    
    #gemini
    async def curl_agent(state:CurlState):
        history=format_history(state["messages"])
        prompt=get_agent_prompt(
            tool_schema=tool_schema,
            history=history,
            agent_prompt=agent_prompt,
            state=state)
        
        response=model.invoke(prompt)
        return await response_route(response)

    #graph
    flow=StateGraph(CurlState)

    flow.add_node("mcp_exec",mcp_exec_node)
    flow.add_node("curl_agent",agent_node)
    flow.add_node("tools",ToolNode([search_tavily]))

    flow.add_edge(START,"curl_agent")
    flow.add_conditional_edges(
        "curl_agent",
        tool_router,
        {
            "mcp_exec": "mcp_exec",
            "tools": "tools",
            END: END
        }
    )
    flow.add_edge("tools","curl_agent")
    flow.add_edge("mcp_exec","curl_agent")
    graph=flow.compile()

    return graph

graph=asyncio.run(init_graph())


if __name__ == "__main__":
    result = asyncio.run(
        graph.ainvoke({
            "messages": [HumanMessage(content="get page www.wikipedia.org and then search for 'elden ring' ")],
            "tool_used": []
        })
    )
    print(result)


#currently the most stable and working agent