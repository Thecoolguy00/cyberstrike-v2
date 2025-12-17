from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState
from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, START, END
from vector import retriever, vector_store
from langgraph.prebuilt import tools_condition
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool

llm = ChatOpenAI(
    model="local-llama",
    openai_api_base="http://127.0.0.1:8080/v1",
    openai_api_key="none"
)

class State(MessagesState):
    context: dict[str, str]

@tool
def retrieve_context(query:str)->dict:
    """
    Retrieve information to help answer a query.

    Args:
    query: The query to search for document retrieval
    """
    retrieved={}
    retrieved_docs = retriever.invoke(query)
    for i,doc in enumerate(retrieved_docs):
        retrieved[i]={"metadata":doc.metadata,"content":doc.page_content} #clean the retreived the data more cleanly and format is properly later
    return retrieved

@tool
def get_retrieved_with_primary_full(query:str)->dict:
    """
    Retrieve information to help answer a query.

    Args:
    query: The query to search for document retrieval
    """
    # Step 1: retrieve initial top-k docs
    retrieved_docs = retriever.invoke(query)
    if not retrieved_docs:
        return {"primary_full_doc": None, "secondary_docs": {}}

    # Step 2: Take the first doc as primary
    primary_meta = retrieved_docs[0].metadata
    primary_qa_id = primary_meta.get("qa_id")

    # Step 3: Fetch ALL chunks of the primary QA from vector store
    primary_full = vector_store.get(where={"qa_id": primary_qa_id})
    primary_chunks = list(zip(primary_full["metadatas"], primary_full["documents"]))

    # Sort primary chunks by chunk index
    primary_chunks = sorted(
        primary_chunks,
        key=lambda x: x[0].get("chunk_index", 0)
    )

    # Merge + dedupe
    seen = set()
    merged_lines = []
    for _, text in primary_chunks:
        for line in text.split("\n"):
            line=line.strip()
            if line and line not in seen:
                merged_lines.append(line)
                seen.add(line)
    primary_text = "\n".join(merged_lines)

    # Step 4: Group remaining QA items from the top-k retrieval
    secondary_group = {}
    for doc in retrieved_docs[1:]:
        meta = doc.metadata
        qa_id = meta.get("qa_id")
        if qa_id == primary_qa_id:
            continue
        secondary_group.setdefault(qa_id, []).append(doc)

    # Step 5: Format secondary docs into clean grouped chunks
    secondary_cleaned = {}
    for qa_id, docs in secondary_group.items():
        sorted_docs = sorted(docs, key=lambda d: d.metadata.get("chunk_index", 0))
        grouped_text = "\n\n".join([d.page_content for d in sorted_docs])
        secondary_cleaned[qa_id] = {
            "metadata": sorted_docs[0].metadata,
            "content": grouped_text
        }

    return {
        "primary_full_doc": {
            "metadata": primary_chunks[0][0],
            "content": primary_text
        },
        "secondary_docs": secondary_cleaned
    }


agent=llm.bind_tools([get_retrieved_with_primary_full])

sys_msg = SystemMessage(content="You must ALWAYS call the get_retrieved_with_primary_full tool first.Do not answer ANY part of the user's query until after a tool response is provided.If the tool returns no results, respond: \"No relevant documentation found.\"If you answer without a tool call, you violate system rules.")

def assistant(state: State):
   return {"messages": [agent.invoke([sys_msg] + state["messages"])]}

flow=StateGraph(State)
flow.add_node("assistant",assistant)
flow.add_node("tools",ToolNode([get_retrieved_with_primary_full]))

flow.add_edge(START,"assistant")
flow.add_conditional_edges("assistant",tools_condition)
flow.add_edge("tools","assistant")
flow.add_edge("assistant",END)

graph=flow.compile()