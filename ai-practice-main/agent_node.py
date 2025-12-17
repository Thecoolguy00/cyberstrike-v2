#agent_node.py
from typing import Dict, TypedDict, List
import os,time
from langchain_core.messages import HumanMessage, BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from groq import APIStatusError
from langgraph.graph import MessagesState
from dotenv import load_dotenv
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from prompt import generate_prompt
from graph_tools import fetch_page, tav_search
from config import TYPE
load_dotenv()

api_key=os.getenv("GEMINI_API_KEY_4","")
groq_key=os.getenv("GROQ_API_KEY","")
tool_list=[tav_search, fetch_page]

class star(MessagesState):
    task: str
    target: str


llm=ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    api_key=api_key,
    temperature=0.5
).bind_tools(tool_list)

groq_llm = ChatGroq(
    model="moonshotai/kimi-k2-instruct-0905",
    api_key=groq_key,
    temperature=0.5
).bind_tools(tool_list)

#adding retry logic for api_error like Rate per Minute, Token Per Minute
@retry(retry=retry_if_exception_type((APIStatusError, Exception)), stop=stop_after_attempt(2), wait=wait_fixed(2))
def send_llm_request(llm, messages):
        try:
           llm
        except Exception as e:
            print("")
            raise e
        except APIStatusError as exe:
            raise exe
        
def agent_node_gemini(state: star):
    """
    agent node
    does the given task on the given target
    """

    task=state["task"]
    target=state["target"]
    messages=state.get("messages",[])

    if not messages:
        messages=[
            HumanMessage(
                content=generate_prompt(task=task, target=target, type=TYPE)
            )
        ]
    # print(f"[AGENT] Sleeping for 15s")
    # time.sleep(15)
    response=llm.invoke(messages)
    return {"messages":messages+[response]}


def agent_node(state: star):
    """
    Agent node using Groq LLM backend
    """
    task = state["task"]
    target = state["target"]
    messages = state.get("messages", [])

    if not messages:
        # initial invocation uses tuple format internally
        initial_prompt = generate_prompt(task=task, target=target, type=TYPE)
        messages = [
            ("system", "You are an agent that solves tasks with tools."),
            ("human", initial_prompt)
        ]

    # print("[AGENT] sleeping 15s before call")
    # time.sleep(15)

    # call Groq LLM using tuple message format
    response = groq_llm.invoke(messages)

    # append returned AIMessage
    return {"messages": messages + [response]}