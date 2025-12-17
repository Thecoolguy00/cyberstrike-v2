from langchain_community.document_loaders import WikipediaLoader
from tavily import TavilyClient
from dotenv import load_dotenv
import os

load_dotenv()
api_key=os.getenv("TAVILY_API_KEY")

def search_wikipedia(wiki_query: str) -> dict:
    """Retrieve docs from Wikipedia."""
    try:
        wiki_docs = WikipediaLoader(query=wiki_query, load_max_docs=2).load()
    except Exception as e:
        return {"error": f"Wikipedia failed: {e}"}

    formatted_docs = "\n\n---\n\n".join(
        [
            f'<Document source="{doc.metadata.get("source","unknown")}" page="{doc.metadata.get("page","")}">\n{doc.page_content}\n</Document>'
            for doc in wiki_docs
        ]
    )

    return {"wikipedia_search_result": formatted_docs}


def search_tavily(tavily_query:str)->str:
    """Search web and give ans to the query"""
    client = TavilyClient(api_key)
    tavily_docs = client.search(
        query=tavily_query,
        include_answer="advanced",
        max_results=4
    )
    
    #formatting
    query=tavily_docs.get("query","")
    answer=tavily_docs.get("answer","")
    results=tavily_docs.get("results",[])

    formatted=[f"QUESTION: {query}",f"ANSWER: {answer}","\nSOURCES:\n"]
    for i,doc in enumerate(results,1):
        title=doc.get("title","").strip()
        url=doc.get("url","").strip()
        content=doc.get("content","").strip().replace("\n"," ")
        formatted.append(
            f"[{i}] {title}\nURL: {url}\nCONTENT: {content[:600]}..."
        )
    
    return "\n\n".join(formatted)


if __name__ == "__main__":
    print(search_tavily("how to ssh into a remote server?"))
    # print("\n\nwikipediasearch:")
    # print(search_wikipedia("how to ssh into a remote server?"))