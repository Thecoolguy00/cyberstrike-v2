from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="local-llama",
    openai_api_base="http://127.0.0.1:8080/v1",
    openai_api_key="none"
)

from langgraph.graph import MessagesState

class sstat(MessagesState):
    summary:str     #this adds another state variable along with messages

from langchain_core.messages import HumanMessage,SystemMessage,RemoveMessage

#logic for calling the llm
def call_llm(state: sstat):
    #first get summary if it's there
    summary=state.get("summary","")
    #if there is a summary, then we add it in the messages state
    if summary:
        #cp the summary to variable summary_message for formatting
        summary_message=f"Summary of our earlier conversation: {summary}"
        #adding the summary_message to the messages state as a system message.....why?
        messages=[SystemMessage(content=summary_message)] + state["messages"]
    else:   
    #if we don't have a summary then assign messages state to messages, wait the messages earlier was just a variable named messages
        messages=state["messages"]
    #we can just pass the state to the invoke here right, no, why? because then you would need to write 2 invokes, one for when summary is there and one for when it isn't
    #so we invoke it here
    response=llm.invoke(messages)
    return {"messages": response}      #appending response to state messages,it's the format for returning in langchain/graph

def summarize_conversation(state: sstat):      
    #I think we will be passing the state sstat which has the data from call_llm node, note that on each run is a diff execution
    #and the MessagesState is not conserved between individual runs(especially when running in notebook)

    #first we get any existing summary from state if present
    summary=state.get("summary","")
    #then according to wehther we have a previous summary we define the new-summary ptompt
    if summary:
        #summary is present, so add that and new messages for extended summary
        summary_prompt={
            f"This is the summary of the conversation to date: {summary}\n\n"
            "Extend the summary by taking the above new messages into account"
        }
    else:
        #generating first summary
        summary_prompt="Create a summary of the converstion above:"
    
    #add the summary_prompt to the current message history i.e state["messages"]
    msg=state["messages"]+[HumanMessage(content=summary_prompt)]
    response=llm.invoke(msg)

    #delete all but last 2 messages
    deleted_messages=[RemoveMessage(id=m.id) for m in state["messages"]]
    return {"summary":response.content, "messages":deleted_messages} #updating the summary and shortened message history

from langgraph.graph import END
def should_continue(state: sstat):

    """Return the next node to execute"""
    messages=state["messages"]
    # print(messages)
    #if there are more than 6 messages then summarize
    if len(messages)>4:
        return "summarize"
    #otherwise we CAN just end
    return END

#as state is transient to a single graph execution, we are unable to do a multi-turn conversation successfully
#so we add memory(persistance) using MemorySaver``

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START

#defining our graph named flow
flow=StateGraph(sstat)
#nodes
flow.add_node("conv",call_llm)
flow.add_node("summarize",summarize_conversation)
#edges
flow.add_edge(START,"conv")
flow.add_conditional_edges("conv",should_continue)
flow.add_edge("summarize",END)

#compiling our graph with memory
memory=MemorySaver()
graph=flow.compile(checkpointer=memory)

#creating a thread where the checkpoints will be saved
config1={"configurable":{"thread_id":"1"}}
graph.invoke({"messages":[HumanMessage(content="My name it Rock Lee")]},config1)
graph.invoke({"messages":[HumanMessage(content="and my age is 24")]},config1)
graph.invoke({"messages":[HumanMessage(content="I like apples")]},config1)
msg_a=HumanMessage(content="what is my name,age and favourite fruit?")

out_12=graph.invoke({"messages":[msg_a]},config1)
# print(out_12['messages'][-1:])
print(out_12)