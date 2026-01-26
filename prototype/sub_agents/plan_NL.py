#plan_NL.py

#This planner returns a natural langauge tasks for each required sub-agent
#later add memory for loop use with context for progressing during a task

import asyncio
from dotenv import load_dotenv
import os, json, operator
from pydantic import BaseModel
from typing import TypedDict, List, Annotated
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph,START, END, MessagesState
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import Field
from prototype.sub_agents.helper import extract_json_block

groq_key=os.getenv("GROQ_API_KEY","")

groq_llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=groq_key,
    temperature=0.5
)

class Task(BaseModel):
    agent:str
    task_description:str

class Plan(BaseModel):
    plan:List[Task]=[]
    final_answer: str = ""

class GraphState(TypedDict):
    query: str
    plan: List[dict]=Field(default_factory=list)
    agent_response_history: dict
    final_answer: str

parser=PydanticOutputParser(pydantic_object=Plan)

def planner(state: GraphState):
    query = state.get("query", "")
    prev_plan = state.get("prev_plan", [])
    prev_results = state.get("agent_response_history", {})

    prompt = f"""
    You are an expert cybersecurity planner operating in an iterative plan–execute–feedback loop.

    IMPORTANT EXECUTION MODEL (READ CAREFULLY):
    - You do NOT generate a full multi-step plan at once.
    - Only ONE logical step (or a small batch of independent steps) will be executed before you are called again.
    - After each task is executed, its result will be added to the history.
    - You will then be called again to decide the NEXT step based on REAL results.
    - NEVER assume the output of a task that has not already been executed.
    - Conditional logic must be handled across multiple planner calls, NOT within a single plan.

    Your job:
    - Given the user query AND the completed task results so far,
    - Decide what to do NEXT.
    - If enough information is already collected, return a final_answer and an empty plan.

    Available agents:
    - nmap_a: perform light, non-intrusive port and service discovery
    - ferox_a: directory and endpoint enumeration
    - curl_a: fetch headers, pages, endpoints
    - xss_a: test for reflected or stored XSS where appropriate

    Previous executed tasks:
    {prev_plan}

    Results from executed tasks:
    {prev_results}

    Rules:
    - for nmap scans, increase the scan power when low scans don't give any results
    - Only include tasks that can be executed NOW based on known results.
    - Do NOT include conditional future tasks in the same plan.
    - If a decision depends on previous output, wait for that output in a future planner call.
    - Plans must be ordered.
    - If no more tasks are needed, return an empty plan and provide final_answer.

    Return ONLY valid JSON in the following schema:
    {parser.get_format_instructions()}

    User query:
    {query}
    """

    
    messages = [
        HumanMessage(content=prompt)
    ]

    # call Groq LLM using tuple message format
    response = groq_llm.invoke(messages)
    #parsing
    parsed=parser.parse(extract_json_block(response.content))

    return {
        "agent_response_history": state["agent_response_history"],
        "plan": [t.model_dump() for t in parsed.plan],
        "final_answer": parsed.final_answer
    }

flow=StateGraph(GraphState)
flow.add_node("planner",planner)

flow.add_edge(START,"planner")
flow.add_edge("planner",END)

graph=flow.compile()

