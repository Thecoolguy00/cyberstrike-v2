import asyncio
from dotenv import load_dotenv
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph, MessagesState, START
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv()

class State(MessagesState):
    pass

api_key_1=os.getenv("GEMINI_API_KEY_1","")
api_key_2=os.getenv("GEMINI_API_KEY_2","")
api_key_3=os.getenv("GEMINI_API_KEY_3","")

    #gemini LLM
master_model=ChatGoogleGenerativeAI(model="gemini-2.5-pro",api_key=api_key_1)   #master model
sub_model_1=ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key_2)  #nmap
sub_model_2=ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key_3)  #curl

    # Local LLM, feroxbuster
# sub_model_3 = ChatOpenAI(
#     model="qwen-local",
#     openai_api_base="http://127.0.0.1:8080/v1",
#     openai_api_key="none",
# )

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
async def init_graph():
    tools = await client.get_tools()
    return tools
    # sys_prompt="you are a recon expert, use the available tools provided to do recon"
    # def call_model(state: State):
    #     response = model.bind_tools(tools).invoke([SystemMessage(content=sys_prompt)]+state["messages"])
    #     return {"messages": response}

    # builder = StateGraph(MessagesState)
    # builder.add_node("call_model", call_model)
    # builder.add_node("tools", ToolNode(tools))
    # builder.add_edge(START, "call_model")
    # builder.add_conditional_edges("call_model", tools_condition)
    # builder.add_edge("tools", "call_model")

    # return builder.compile()


# Export graph for LangGraph runtime (important!)
# graph = asyncio.run(init_graph())
tool_list=asyncio.run(init_graph())

# for i in tool_list:
#     print(f"\n\n----------------------------------------\n{i}")

def agent(state:State):
    sys_prompt="you are a recon expert, use the available tools provided to do recon"
    response = sub_model_1.bind_tools(tool_list).invoke([SystemMessage(content=sys_prompt)]+state["messages"])
    return {"messages": response}
  
builder = StateGraph(State)
builder.add_node("call_model", agent)
builder.add_node("tools", ToolNode(tool_list))
builder.add_edge(START, "call_model")
builder.add_conditional_edges("call_model", tools_condition)
builder.add_edge("tools", "call_model")

graph=builder.compile()

# Optional: Run manually
if __name__ == "__main__":
    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="perform a basic nmap scan on 127.0.0.1")]}))
    print(result)
