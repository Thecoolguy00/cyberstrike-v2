from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
import random, json

class State(MessagesState):
    pass

llm = ChatGoogleGenerativeAI(...)

def main_agent(state):
    prompt = "..."   # your multi-tool schema prompt
    response = llm.invoke([prompt])
    return response_route_multi(response)

def multi_router(state):
    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", None)

    if not calls:
        return END

    return [c["name"] for c in calls]

# Build graph
graph = StateGraph(State)

graph.add_node("main_agent", main_agent)
graph.add_node("nmap_scan", ToolNode([nmap_tool]))
graph.add_node("feroxbuster", ToolNode([ferox_tool]))
graph.add_node("nuclei_scan", ToolNode([nuclei_tool]))

graph.add_edge(START, "main_agent")
graph.add_conditional_edges("main_agent", multi_router)

graph.add_edge("nmap_scan", "main_agent")
graph.add_edge("feroxbuster", "main_agent")
graph.add_edge("nuclei_scan", "main_agent")

compiled = graph.compile()
