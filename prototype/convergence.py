import asyncio
from dotenv import load_dotenv
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph, MessagesState, START
from langchain_core.messages import SystemMessage
load_dotenv()

class State(MessagesState):
    pass

api_key_1=os.getenv("GEMINI_API_KEY_1","")
api_key_2=os.getenv("GEMINI_API_KEY_2","")
api_key_3=os.getenv("GEMINI_API_KEY_3","")

init_models=False

if init_models:
    #gemini LLM
    model_1=ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key_1)   #master model
    model_2=ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key_2)  #nmap
    model_3=ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key_3)  #curl

    # Local LLM, feroxbuster
    model_4 = ChatOpenAI(
        model="qwen-local",
        openai_api_base="http://127.0.0.1:8080/v1",
        openai_api_key="none",
    )

# MCP client (async init)
client = MultiServerMCPClient(
    {
        "combined_tools": {
            "url": "http://192.168.26.128:4545/mcp",
            "transport": "streamable_http",
        }
    }
)

#generally we get the available tools that the mcp expose, but for testing we will use a list since we know which tools the mcp has
# async def init_graph():
#     tools = await client.get_tools()
#     full code here and return the graph object to the langgraph studio as return builder.compile(),

# Export graph for LangGraph runtime (important!)
# graph = asyncio.run(init_graph())

#now why are we aysncing it? because the mcp server is async or something like that


