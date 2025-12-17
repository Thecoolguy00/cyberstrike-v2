from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph, START, END
from langchain_core.messages import HumanMessage, SystemMessage, RemoveMessage, AIMessage



                            # SELF LOOP DOESN'T WORK IN LANGGRAPH, 
                            # LANGGRAPH IS MADE FOR DIRECTED ACYCLIC GRAPH (DAG)


# Initialize local LLM
llm = ChatOpenAI(
    model="local-llama",
    openai_api_base="http://127.0.0.1:8080/v1",
    openai_api_key="none"
)

# Custom state to hold messages and summary
class sstat(MessagesState):
    summary: str

# LLM conversation node
def call_llm(state: sstat):
    summary = state.get("summary", "")
    messages = state["messages"]

    # prepend system summary if available
    if summary:
        summary_message = f"Summary of our earlier conversation: {summary}"
        messages = [SystemMessage(content=summary_message)] + messages

    response = llm.invoke(messages)
    # wrap it as a message list
    return {"messages": [AIMessage(content=response.content)]}

# Summarization node
def summarize_conversation(state: sstat):
    summary = state.get("summary", "")
    if summary:
        summary_prompt = (
            f"This is the current summary: {summary}\n\n"
            "Extend or refine it based on the following new human messages."
        )
    else:
        summary_prompt = "Create an initial concise summary of the human messages so far."

    # collect human messages
    human_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage)]
    msgs = human_msgs + [HumanMessage(content=summary_prompt)]
    
    response = llm.invoke(msgs)
    # remove older messages, keep only the updated summary
    deleted = [RemoveMessage(id=m.id) for m in state["messages"]]
    return {"summary": response.content, "messages": deleted}

# Decide next node
def should_continue(state: sstat):
    messages = state["messages"]
    last_msg = messages[-1].content.lower().strip()

    # exit condition
    for w in ["quit", "end"]:
        if w in last_msg:
            return END

    # summarization trigger
    if len(messages) > 4:
        return "summarize"

    return "conv"

# Build the graph
flow = StateGraph(sstat)

flow.add_node("conv", call_llm)
flow.add_node("summarize", summarize_conversation)

# Execution flow
flow.add_edge(START, "conv")
flow.add_conditional_edges("conv", should_continue, {
    "summarize": "summarize",
    "conv": "conv",
    END: END
})
flow.add_edge("summarize", "conv")

graph = flow.compile()
