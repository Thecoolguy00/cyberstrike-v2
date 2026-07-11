
#helper functions for the framwork

#This function takes a langgraph tool list and converts it into a NL tool schema
from pydantic_core import PydanticUndefined

def extract_tool_Schema(tools: list):
    """Convert LangChain or MCP tools into a readable NL schema."""
    schema_lines = []

    for t in tools:
        name = getattr(t, "name", "unknown")
        desc = getattr(t, "description", "No description").strip().split("\n")[0]

        # MCP TOOL BRANCH ----------------------------------------------
        if hasattr(t, "inputSchema") and isinstance(t.inputSchema, dict):
            args_schema = t.inputSchema
            props = args_schema.get("properties", {})
            required = set(args_schema.get("required", []))

            arg_lines = []
            for arg, spec in props.items():
                typ = spec.get("type", "any")
                default = spec.get("default")

                if arg in required:
                    req = "required"
                elif default is not None:
                    req = f"default={default!r}"
                else:
                    req = "optional"

                arg_lines.append(f"{arg} ({typ}, {req})")

            args_str = ", ".join(arg_lines) if arg_lines else "none"

        # LANGCHAIN StructuredTool BRANCH -------------------------------
        elif hasattr(t, "args_schema"):
            fields = t.args_schema.model_fields
            arg_lines = []
            for arg, finfo in fields.items():
                ann = finfo.annotation
                typ = ann.__name__ if hasattr(ann, "__name__") else str(ann)
                if finfo.is_required():
                    req = "required"
                elif finfo.default is not None:
                    req = f"default={finfo.default!r}"
                else:
                    req = "optional"

                arg_lines.append(f"{arg} ({typ}, {req})")

            args_str = ", ".join(arg_lines) if arg_lines else "none"

        # UNKNOWN?
        else:
            args_str = "none"

        schema_lines.append(f"{name}: {desc}\n  args: {args_str}")

    return "TOOLS:\n" + "\n\n".join(schema_lines)



#formats the message state history into a more simpler readable format
def format_history(msgs)->str:
    """Takes state["messages"] as parameter and returns a clean, formatted history"""
    out = []
    for m in msgs:
        cls = m.__class__.__name__

        if cls == "HumanMessage":
            out.append(f"user: {m.content}")

        elif cls == "AIMessage":
            if getattr(m, "tool_calls", None):
                # tool call happened
                for tc in m.tool_calls:
                    name = tc.get("name")
                    args = tc.get("args")
                    out.append(f"assistant(tool_call): {name}{args}")
            else:
                out.append(f"assistant: {m.content}")

        elif cls == "ToolMessage":
            out.append(f"tool({m.name}): {m.content}")

        else:
            out.append(f"unknown_message_type: {m}")
    return "\n".join(out)


#extracts json
def extract_json_block(text: str):
    """Extracts Clean Json block from the given JSON String with other garbage"""
    start = text.find("{")
    if start == -1:
        return None

    stack = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            stack += 1
        elif text[i] == "}":
            stack -= 1
            if stack == 0:
                return text[start:i+1]

    return None


#custom message router for tool_calls
import json, random, uuid, asyncio
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from prototype.sub_agents.true_mcp_exec import get_mcp_tools, run_mcp_tool

MCP_TOOLS=[t.name for t in asyncio.run(get_mcp_tools())]
async def response_route(a:BaseMessage):
    """
    If LLM requests and tool call then tool call( we have our own schema for llm output) then generates an synthetic AIMessage(tool_call).
    Otherwise return normal AIMessage.
    """
    json_str = extract_json_block(a.content)
    if not json_str:
        # no JSON found -> treat whole message as a normal AI reply
        return {"messages": [a], "tool_used": []}
    
    # safe JSON parse
    try:
        con = json.loads(json_str)
    except Exception:
        # If somehow still invalid JSON, treat as normal reply
        return {"messages": [a], "tool_used": []}
    
    
    tool_used=con.get("tool","")
    args = con.get("args", {})

    tool_call_id=str(uuid.uuid4())
    if tool_used:

        #synthetic AIMessage(tool call)
        ai_tool_call_msg=AIMessage(content="", 
                additional_kwargs={'tool_calls': [{'id': tool_call_id, 'function': {'arguments': json.dumps(args), 'name': tool_used}, 'type': 'function'}], 'refusal': None},
                response_metadata={'service_tier': None, 'finish_reason': 'tool_calls', 'logprobs': None},
                tool_calls=
                [
                    {
                        'name': tool_used, 
                        'args': args, 
                        'id': tool_call_id, 
                        'type': 'tool_call'
                    }
                ], 
                        usage_metadata={'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0, 'input_token_details': {}, 'output_token_details': {}}
                )
        
        return {"messages":[ai_tool_call_msg],"tool_used":[tool_used]}
    
    # no tool call -> normal AI reply
    return {"messages": [a],"tool_used":[]}


#returns a langchain structured tool list from normal function list
from langchain.tools import StructuredTool
def get_structured_tool(tools:list)->list:
    """Returns a langchain structured tool list from normal function list"""
    langchain_tool=[]
    for i in tools:
        langchain_tool.append(StructuredTool.from_function(i))
    
    return langchain_tool


#NL tool schema from function list
def tool_schema_from_func(tools:list):
    """Returns NL tool schema from a python function list"""
    structured_tools=get_structured_tool(tools)
    tool_schema=extract_tool_Schema(structured_tools)

    return tool_schema


#new function, why? :- because i've not tired mcp tools with our custom tool flow design --bummers
#problem: .bind_tools() converts mcp tools into callable tools
#solution: maually converting mcp_tools into callable tools by making custom langchain structured tool

from langgraph.graph import MessagesState, END, START
import operator
from typing import Annotated, List

class GraphState(MessagesState):
    tool_used:Annotated[List[str],operator.add]

# --- Background task detection ---
# MCP tools that start background tasks and return {"task_id": ..., "status": "started"}
BG_TASK_TOOLS = {"start_nmap_long_scan", "start_feroxbuster"}

async def mcp_exec_node(state: GraphState):
    """A node for executing mcp tool calls.
    
    Detects background task responses and sets _bg_task_info in state
    so the graph can route to schedule_callback instead of back to the agent.
    """
    # Get last message
    last = state["messages"][-1]

    # Safety checks
    if not isinstance(last, AIMessage):
        return {}

    if not last.tool_calls:
        return {}

    call = last.tool_calls[0]
    tool_used = call["name"]
    args = call["args"]
    tool_call_id = call["id"]

    # Execute MCP tool
    mcp_result = await run_mcp_tool(
        tool_name=tool_used,
        args=args
    )

    # Detect background task start
    bg_task_info = None
    if tool_used in BG_TASK_TOOLS:
        try:
            parsed = json.loads(mcp_result)
            if parsed.get("status") == "started" and parsed.get("task_id"):
                bg_task_info = {
                    "task_id": parsed["task_id"],
                    "tool": tool_used,
                    "started": True,
                }
        except (json.JSONDecodeError, AttributeError):
            pass

    result = {
        "messages": [
            ToolMessage(
                name=tool_used,
                content=mcp_result,
                tool_call_id=tool_call_id
            )
        ],
        "tool_used": []
    }

    # Set background task info if detected (single object, not multiple flags)
    if bg_task_info:
        result["_bg_task_info"] = bg_task_info

    return result


def mcp_result_router(state: GraphState):
    """
    Routes after mcp_exec_node.
    If a background task was just started → schedule_callback node.
    Otherwise → back to agent LLM.
    
    Note: The "agent" return value is a logical name. Each graph maps
    it to its own agent node (e.g., "nmap_agent", "ferox_agent").
    """
    bg_info = state.get("_bg_task_info")
    if bg_info and bg_info.get("started"):
        return "schedule_callback"
    return "agent"


def tool_router(state: GraphState):
    if not state["messages"]:
        return END

    last = state["messages"][-1]

    if not isinstance(last, AIMessage) or not last.tool_calls:
        return END

    tool_name = last.tool_calls[0]["name"]

    if tool_name in MCP_TOOLS:
        return "mcp_exec"

    return "tools"

#extracting text from different message schema
def extract_text(msg) -> str:
    if isinstance(msg, str):
        return msg

    if isinstance(msg, list):
        out = []
        for part in msg:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict) and "text" in part:
                out.append(part["text"])
        return "\n".join(out)

    return str(msg)

