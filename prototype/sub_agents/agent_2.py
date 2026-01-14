from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.graph import START, StateGraph, MessagesState
from langgraph.prebuilt import tools_condition, ToolNode
import json, os, re, random
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from util import response_route, tool_schema_from_func, format_history
from p0_template import get_agent_prompt
load_dotenv()
api_key_1=os.getenv("GEMINI_API_KEY_1","")
llm=ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key_1)

#       This agent has a custom router for message and toolcalls
#       With this we can allow llm to update our custom parameters even during a tool_call

def add(a: int, b: int) -> int:
    """Adds a and b.

    Args:
        a: first int
        b: second int
    """
    return a + b

def multiply(a: int, b: int) -> int:
    """Multiplies a and b.

    Args:
        a: first int
        b: second int
    """
    return a * b

def divide(a: int, b: int) -> float:
    """Divide a and b.

    Args:
        a: first int
        b: second int
    """
    return a / b

def increment(z: int)->int:
    """
    Increments z by 1

    Args:
        z:int
    """
    z=z+1
    return z
tools = [add, multiply, divide, increment]
tool_schema=tool_schema_from_func(tools)

from langchain_openai import ChatOpenAI

# llm = ChatOpenAI(
#     model="qwen-local",
#     openai_api_base="http://127.0.0.1:8080/v1",
#     openai_api_key="none"
# )

from typing import List,Annotated
import operator
class GraphState(MessagesState):
    tool_used:Annotated[List[str],operator.add]

# Node
import textwrap
def assistant(state: GraphState):
    clean_schema = textwrap.indent(tool_schema.strip(), "    ")
    clean_history = textwrap.indent(format_history(state["messages"]).strip(), "    ")
    agent_prompt="You are an assistant that performs arithmetic using tools."
    clean_agent_prompt=textwrap.indent(agent_prompt,"   ")
    prompt=get_agent_prompt(
        tool_schema=clean_schema,
        history=clean_history,
        agent_prompt=clean_agent_prompt,
        state=state)
    response=llm.invoke([prompt])
    return response_route(response)

# Build graph
builder = StateGraph(GraphState)
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(tools))
builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant",tools_condition)
builder.add_edge("tools", "assistant")

# Compile graph
graph = builder.compile()


# config1={"configurable":{"thread_id":"1"}}
# output=graph.invoke({"messages":[HumanMessage(content="multiply 123123 and 123213, then add the result with 100000000")]},config1)

# print(output)