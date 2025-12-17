from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.graph import START, StateGraph, MessagesState
from langgraph.prebuilt import tools_condition, ToolNode
import json, os, re, random
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
load_dotenv()
api_key_1=os.getenv("GEMINI_API_KEY_1","")
llm=ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key_1)

#       This agent has a custom router for message and toolcalls
#       With this we can allow llm to update our custom parameters even during a tool_call

def format_history(msgs):
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

def add(a: int, b: int) -> int:
    """Adds a and b.

    Args:
        a: first int
        b: second int
    """
    return a + b

def multiply(a: int, b: int) -> int:
    """Multiplies a and b.

    Args:
        a: first int
        b: second int
    """
    return a * b

def divide(a: int, b: int) -> float:
    """Divide a and b.

    Args:
        a: first int
        b: second int
    """
    return a / b

def increment(z: int)->int:
    """
    Increments z by 1

    Args:
        z:int
    """
    z=z+1
    return z
tools = [add, multiply, divide, increment]

from langchain_openai import ChatOpenAI

# llm = ChatOpenAI(
#     model="qwen-local",
#     openai_api_base="http://127.0.0.1:8080/v1",
#     openai_api_key="none"
# )

from typing import List,Annotated
import operator
class GraphState(MessagesState):
    tool_used:Annotated[List[str],operator.add]

# Node
def assistant(state: GraphState):
   prompt=f"""
        RESPONSE SCHEMA (choose exactly one):

        1. NORMAL RESPONSE
        {{
            "thinking": "explain your reasoning step-by-step",
            "message": "natural language reply for the user"
        }}

        2. TOOL CALL
        {{
            "thinking": "explain why a tool call is needed",
            "tool_name": "string tool name",
            "args": {{ "key": value, "key": value }}   // dict of arguments required by that tool
        }}

        RULES:
        - Use ONLY one schema per reply.
        - NEVER mix "message" with tool calls.
        - NEVER use a tool if the result is already in the history.
        - NEVER call a tool twice for the same arguments.
        - Respond JSON ONLY. No text outside JSON Block.

        You are an assistant that performs arithmetic using tools.

        Tools:
        - add(a, b): returns a + b
        - subtract(a, b): returns a - b
        - multiply(a, b): returns a * b
        - increment(z): returns z + 1

        History:
        {format_history(state["messages"])}

        Tools used so far:
        {state["tool_used"]}
        """
   response=llm.invoke([prompt])
   json_str = re.search(r'\{[\s\S]*\}', response.content).group(0)
   con=json.loads(json_str)
   tool_used=con.get("tool_name","")
   unique_id=tool_used+str(random.randint(0,1000))
   print(f"\n\n{state}\n\n")
   if tool_used:
      tool_msg=AIMessage(content="", 
                additional_kwargs={'tool_calls': [{'id': unique_id, 'function': {'arguments': f'{con.get("args")}', 'name': tool_used}, 'type': 'function'}], 'refusal': None},
                response_metadata={'service_tier': None, 'finish_reason': 'tool_calls', 'logprobs': None},
                tool_calls=
                [
                    {
                        'name': tool_used, 
                        'args': con.get("args"), 
                        'id': unique_id, 
                        'type': 'tool_call'
                    }
                ], 
                        usage_metadata={'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0, 'input_token_details': {}, 'output_token_details': {}}
                )
      return {"messages":[tool_msg],"tool_used":[tool_used]}
   return {"messages": [response],"tool_used":[]}

# Build graph
builder = StateGraph(GraphState)
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(tools))
builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant",tools_condition)
builder.add_edge("tools", "assistant")

# Compile graph
graph = builder.compile()


# config1={"configurable":{"thread_id":"1"}}
# output=graph.invoke({"messages":[HumanMessage(content="multiply 123123 and 123213, then add the result with 100000000")]},config1)

# print(output)