import asyncio
from dotenv import load_dotenv
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph, MessagesState, START
from langchain_core.messages import SystemMessage, HumanMessage

#---------------Agents and planner-------------------#
from curl_graph_test_mcp import graph as curl_a
from nmap_graph_test_mcp import graph as nmap_a
from ferox_graph_test_mcp import graph as ferox_a
from plan_NL import graph as planner


load_dotenv()
class State(MessagesState):
    pass

# Local LLM
# model_4 = ChatOpenAI(
#     model="qwen-local",
#     openai_api_base="http://127.0.0.1:8080/v1",
#     openai_api_key="none",
# )

def nmap_agent(task:str)->str:
    result=asyncio.run(nmap_a.ainvoke({"messages":[HumanMessage(content=task)],"tool_used":[]}))
    return result

def curl_agent(task:str)->str:
    result=asyncio.run(curl_a.ainvoke({"messages":[HumanMessage(content=task)],"tool_used":[]}))
    return result

def ferox_agent(task:str)->str:
    result=asyncio.run(ferox_a.ainvoke({"messages":[HumanMessage(content=task)],"tool_used":[]}))
    return result

def plan(query:str):
    plan=planner.invoke({"query":query})
    return plan

current_plan=plan("active recon on target 127.0.0.1")["plan"]

print(f"Starting Master")

agent_response={}
for t in current_plan:
    agent=t["agent"]
    description=t["task_description"]
    print(f"\n\nExecuting {agent} : {description}\n\n")
    if agent=="nmap_a":
        response=nmap_agent(description)
        print(response)
    elif agent=="curl_a":
        response=curl_agent(description)
        print(response)
    elif agent=="ferox_a":
        response=ferox_agent(description)
        print(response)
    
    agent_response[agent]=response

print(f"\n\n==================\nAgent Responses\n======================\n{agent_response}")
