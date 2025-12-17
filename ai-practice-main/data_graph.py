#data_graph.py
from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode, tools_condition

from agent_node import agent_node
from graph_tools import fetch_page, tav_search
from agent_node import star

flow=StateGraph(star)

flow.add_node("agent",agent_node)
flow.add_node("tools",ToolNode([tav_search, fetch_page]))

flow.add_edge(START,"agent")
flow.add_conditional_edges(
    "agent",
    tools_condition,
    {
        "tools":"tools",
        END:END,
    }
)

flow.add_edge("tools","agent")

graph=flow.compile()#TODO increase the recursive limit