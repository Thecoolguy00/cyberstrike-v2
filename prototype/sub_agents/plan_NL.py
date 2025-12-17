
#This planner returns a natural langauge tasks for each required sub-agent
#later add memory for loop use with context for progressing during a task

import asyncio
from dotenv import load_dotenv
import os, json, operator
from pydantic import BaseModel
from typing import TypedDict, List, Annotated
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph,START, END, MessagesState
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from util import extract_json_block

load_dotenv()
api_key_1=os.getenv("GEMINI_API_KEY_1","")
model=ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key_1)

class Task(BaseModel):
    agent:str
    task_description:str

class Plan(BaseModel):
    plan:List[Task]

class GraphState(TypedDict):
    query:str
    plan:Annotated[List[dict],operator.add]
    output:str

parser=PydanticOutputParser(pydantic_object=Plan)

def planner(state:GraphState):
    query=state.get("query","")
    prompt=f"""
            You are a expert cybersecurity planner.
            Your job is to break the user query into high-level natural language tasks and give follow-up tasks
            follow-up tasks should be given based on previous given tasks and thier result (if previous tasks are present)
            Tasks are for these agents:
            - nmap_a: performs nmap-related tasks (be as less intrusive as possible)
            - ferox_a: performs directory brute-force and web enumeration
            - curl_a: retrieves headers, pages, endpoints

            example for plan:
            query: do a active recon on 127.0.0.1 using available tools
            nmap_a: scan 127.0.0.1 and find general open ports and their service version
            ferox_a: run a directory listing on http://127.0.0.1/ and find any exposed files and directories
            curl_a: if present, Fetch the /login page

            Previous tasks:
            {state['plan']}

            Return only JSON with the below schema:
            {parser.get_format_instructions()}

            query:{query}
    """

    response=model.invoke(prompt)
    
    #parsing
    parsed=parser.parse(extract_json_block(response.content))
    return {
        "plan":[t.model_dump() for t in parsed.plan],
        "output":json.dumps(parsed.model_dump(),indent=2)
    }

flow=StateGraph(GraphState)
flow.add_node("planner",planner)

flow.add_edge(START,"planner")
flow.add_edge("planner",END)

graph=flow.compile()

