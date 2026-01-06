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
from util import extract_json_block

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
    plan: List[dict]
    agent_response_history: dict
    final_answer: str

parser=PydanticOutputParser(pydantic_object=Plan)

def planner(state: GraphState):
    query = state.get("query", "")
    prev_plan = state.get("prev_plan", [])
    prev_results = state.get("agent_response_history", {})

    prompt=f"""
            You are a expert cybersecurity planner.
            Your job is to break the user query into high-level natural language tasks and give follow-up tasks
            follow-up tasks should be given based on previous given tasks and thier corresponding agent responses (if previous tasks are present)
            Tasks are for these agents:
            - nmap_a: performs nmap-related tasks (be as less intrusive as possible)
            - ferox_a: performs directory brute-force and web enumeration
            - curl_a: retrieves headers, pages, endpoints
            - xss_a: checks if the target url is vulnerable to Cross Site Scripting(XSS)

            example for plan:
            query: do a active recon on 127.0.0.1 using available tools
            nmap_a: scan 127.0.0.1 and find general open ports and their service version
            ferox_a: run a directory listing on http://127.0.0.1/ and find any exposed files and directories
            curl_a: if present, Fetch the /login page
            xss_a: check if https://example.com is vulerable to XSS

            Previous tasks:
            {prev_plan}

            Previous tasks agent responses:
            {prev_results}

            Return only JSON with the below schema:
            {parser.get_format_instructions()}

            When the task is completed, return:
            {{
                "plan": [],
                "final_answer": "<your final analytic output>"
            }}

            query:{query}
        """
    
    messages = [
        ("human", prompt)
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

