# langgraph_browser_tool.py
import asyncio, json
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from playwright_agent_runner import run_session

class GraphState(TypedDict):
    goal: str
    url: str
    result: dict

def browser_agent_node(state: GraphState):
    url = state.get("url")
    goal = state.get("goal")
    # run a short session headful for debugging
    res = run_session(url, goal, headless=True, max_steps=6)
    return {"result": res}

def build_graph():
    g = StateGraph(GraphState)
    g.add_node("browser_agent", browser_agent_node)
    g.add_edge(START, "browser_agent")
    g.add_edge("browser_agent", END)
    return g.compile()

if __name__ == "__main__":
    g = build_graph()
    out = g.invoke({"url": "https://example.com", "goal": "search for login"})
    print(json.dumps(out, indent=2))
