# plan_NL.py
"""
Iterative planner for cybersecurity task orchestration.
Uses plan-execute-feedback loop for adaptive task generation.
"""

import os
from typing import List, TypedDict, Dict
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from util import extract_json_block
import dc_logger

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))

load_dotenv()

# LLM setup
groq_llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=os.getenv("GROQ_API_KEY", ""),
    temperature=0.3
)

#schema
class Task(BaseModel):
    """single task for an agent"""
    agent:str=Field(...,description="Agent name: nmap_a, ferox_a, curl_a, xss_a")
    task_descriptiom:str=Field(...,description="Clear, specific task for the agent")

class Plan(BaseModel):
    """Plan containing tasks and optional final answer"""
    plan: List[Task]=Field(
        default_factory=list,
        description="Next tasks to execute (empty if done)"
    )
    final_answer:str=Field(
        default="",
        description="Summary answer when complete"
    )


class GraphState(TypedDict):
    """Graph State"""
    query:str
    plan:List[dict]
    execution_history: List[Dict[str, str]] #list of {agent, task, result}
    final_answer:str

#parser
parser=PydanticOutputParser(pydantic_object=Plan)


#planner prompt
def get_planner_system_prompt()->str:
    """System prompt defining planner role and rules."""
    return """You are an expert penetration testing planner using an iterative plan-execute-feedback strategy.

EXECUTION MODEL:
- Generate ONE step (or small batch of independent steps) at a time
- After execution, results are added to history and you're called again
- Base NEXT steps on ACTUAL results, not assumptions
- Handle conditionals across multiple planning cycles

AVAILABLE AGENTS:
- nmap_a - Port/service discovery (start light, escalate if needed)
- curl_a - HTTP inspection (headers, pages, endpoints)
- ferox_a - Directory/file enumeration (only on confirmed web services)
- xss_a - XSS testing (only on confirmed input points)

PLANNING RULES:
1. Only plan tasks executable NOW with current knowledge
2. Never assume outputs of unexecuted tasks
3. Order tasks logically (dependencies first)
4. Escalate scan intensity when light scans yield nothing
5. When objective is met, return empty plan + final_answer

OUTPUT FORMAT:
""" + parser.get_format_instructions()


def get_planner_user_prompt(query:str, execution_history:List[Dict[str,str]])->str:
    """User prompt with current state and query"""

    #format executin history with clear task-result mapping
    if not execution_history:
        history_str="None yet - this is the first planning cycle"
    else:
        history_items=[]
        for i, ex in enumerate(execution_history, 1):
            #truncate long results for readability
            result=ex.get("result","No result")
            result_preview=(
                result[:200]+"..." if len(result)>200 else result
            )
            history_items.append(
                f"{i}. [{ex['agent']}] {ex['task']}\n"
                f"   ➜ Result: {result_preview}"
            )
            history_str="\n\n".join(history_items)
        
    return f"""OBJECTIVE:
{query}

EXECUTION HISTORY (Task → Result):
{history_str}

Based on the execution history above, what should happen NEXT?
- If more info needed: Return next task(s) in "plan"
- If objective complete: Return empty "plan" + summary in "final_answer"

IMPORTANT: Each task above shows its result. Don't repeat tasks that already succeeded.
"""

#planning logic

def planner(state: GraphState)->GraphState:
    """
    Plan next tasks based on current state

    Args:
        state: Current graph state with query and execution history

    Returns:
        Updated state with new plan or final answer
    """
    query=state.get("query", "")
    execution_history=state.get("execution_history",[])

    #build messages
    messages=[
        SystemMessage(content=get_planner_system_prompt()),
        HumanMessage(content=get_planner_user_prompt(query, execution_history))
    ]

    #invoke llm
    try:
        response=groq_llm.invoke(messages)
        parsed=parser.parse(extract_json_block(response.content))

        return {
            "query": query,
            "execution_history": execution_history,
            "plan": [t.model_dump() for t in parsed.plan],
            "final_answer": parsed.final_answer
        }
    
    except Exception as e:
        #fallback on error
        logger.error(f"PLan failed {e}")
        logger.info(f"Raw response {response.content if 'resonse' in locals() else 'N/A'}")

        return {
            "query":query,
            "execution_history":execution_history,
            "plan":[],
            "final_answer": f"Error: Planner failed - {str(e)}"
        }
    

#graph constuction
flow=StateGraph(GraphState)
flow.add_node("planner",planner)
flow.add_edge(START, "planner")
flow.add_edge("planner",planner)

graph=flow.compile()


#helper function

def plan_next_step(
        query:str,
        execution_history: List[Dict[str,str]]=None
)->dict:
    """
    Convenience function to get next plan.
    
    Args:
        query: Original penetration testing objective
        execution_history: List of execution records
            Each record: {"agent": str, "task": str, "result": str}
    
    Returns:
        Dict with:
            - plan: List[dict] - Next tasks to execute
            - final_answer: str - Summary if complete
            - is_complete: bool - Whether planning is done
    
    Example:
        >>> result = plan_next_step(
        ...     query="Scan 192.168.1.1",
        ...     execution_history=[
        ...         {"agent": "nmap_a", "task": "Basic scan", "result": "Port 22 open"}
        ...     ]
        ... )
        >>> print(result["plan"])
        [{"agent": "curl_a", "task_description": "Check HTTP on port 80"}]
    """

    state={
        "query":query,
        "plan":[],
        "execution_history": execution_history or [],
        "final_answer":""
    }

    result=graph.invoke(state)

    return {
        "plan":result.get("plan",[]),
        "final_answer": result.get("final_answer",""),
        "is_complete": bool(result.get("final_answer")) or not result.get("plan")
    }