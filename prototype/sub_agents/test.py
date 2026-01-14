#test.py
import asyncio
from dotenv import load_dotenv
import os, json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph, MessagesState, START
from langchain_core.messages import SystemMessage, HumanMessage, AnyMessage

#---------------Agents and planner-------------------#
from curl_graph_test_mcp import graph as curl_a
from nmap_graph_test_mcp import graph as nmap_a
from ferox_graph_test_mcp import graph as ferox_a
from xss_graph_test_mcp import graph as xss_a
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
def extract(a:dict)->str:
    data=a["messages"][-1].content
    loaded=json.loads(data)
    return loaded["message"]

def nmap_agent(task:str)->str:
    result=asyncio.run(nmap_a.ainvoke({"task":task,"messages":[],"tool_used":[]}))
    return extract(result)

def curl_agent(task:str)->str:
    result=asyncio.run(curl_a.ainvoke({"task":task,"messages":[],"tool_used":[]}))
    return extract(result)

def ferox_agent(task:str)->str:
    result=asyncio.run(ferox_a.ainvoke({"task":task,"messages":[],"tool_used":[]}))
    return extract(result)

def xss_agent(task:str)->str:
    result=asyncio.run(xss_a.ainvoke({"task":task,"messages":[],"tool_used":[]}))
    return extract(result)

def plan(query:str,agent_response:dict, prev_plan:list=None):
    plan=planner.invoke({"query":query,"agent_response_history":agent_response, "prev_plan":prev_plan})
    return plan

query = "try to find as much info on target 10.80.171.108"

# First plan
planner_out = plan(query, agent_response={})
current_plan = planner_out["plan"]

print("Starting Master")

while True:
    agent_response = {}
    # If planner has decided we are done
    if len(current_plan) == 0:
        print("\n=== FINAL ANSWER ===")
        print(planner_out["final_answer"])
        break

    # Execute tasks
    for task in current_plan:
        agent = task["agent"]
        desc = task["task_description"]

        print(f"\nExecuting {agent}: {desc}\n")

        if agent == "nmap_a":
            response = nmap_agent(desc)
        elif agent == "curl_a":
            response = curl_agent(desc)
        elif agent == "ferox_a":
            response = ferox_agent(desc)
        elif agent == "xss_a":
            pass
        else:
            response = f"Unknown agent '{agent}'"

        agent_response[agent] = response

    # Replan using the updated agent responses
    planner_out = plan(query=query, agent_response=agent_response,prev_plan=current_plan)
    current_plan = planner_out["plan"]
