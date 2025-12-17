from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="qwen-local",
    openai_api_base="http://127.0.0.1:8080/v1",
    openai_api_key="none"
)

from langgraph.graph import MessagesState

class sstat(MessagesState):
    summary:str

from langchain_core.messages import HumanMessage,SystemMessage,RemoveMessage

def call_llm(state: sstat):
    summary=state.get("summary","")
    if summary:
        summary_message=f"Summary of our earlier conversation: {summary}"
        messages=[SystemMessage(content=summary_message)] + state["messages"]
    else:
        messages=state["messages"]
    response=llm.invoke(messages)
    return {"messages": response}

def summarize_conversation(state: sstat):
    summary=state.get("summary","")
    if summary:
        summary_prompt={
            f"This is the summary of the conversation to date: {summary}\n\n"
            "Extend the summary by taking the above new messages into account"
        }
    else:
        summary_prompt="Create a summary of the converstion above:"
    msg=state["messages"]+[HumanMessage(content=summary_prompt)]
    response=llm.invoke(msg)
    deleted_messages=[RemoveMessage(id=m.id) for m in state["messages"]]
    return {"summary":response.content, "messages":deleted_messages}

from langgraph.graph import END
def should_continue(state: sstat):
    messages=state["messages"]
    if len(messages)>4:
        return "summarize"
    return END

from langgraph.graph import StateGraph, START

flow=StateGraph(sstat)
flow.add_node("conv",call_llm)
flow.add_node("summarize",summarize_conversation)
flow.add_edge(START,"conv")
flow.add_conditional_edges("conv",should_continue)
flow.add_edge("summarize",END)

graph=flow.compile()

# config1={"configurable":{"thread_id":"1"}}
# graph.invoke({"messages":[HumanMessage(content="My name it Rock Lee")]},config1)
# graph.invoke({"messages":[HumanMessage(content="and my age is 24")]},config1)
# graph.invoke({"messages":[HumanMessage(content="I like apples")]},config1)
# msg_a=HumanMessage(content="what is my name,age and favourite fruit?")

# out_12=graph.invoke({"messages":[msg_a]},config1)
# print(out_12[-1:])