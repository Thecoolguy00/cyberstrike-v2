#gprah_tools.py
from langchain.tools import tool

@tool
def fetch_page(url: str):
    """Fetch and return a clean webpage"""

    return get_page(url)

import json
from pathlib import Path
from datetime import datetime
from config import TYPE
from typing import Any, Dict, List

DATA_DIR = Path("data")

def save_data(text: str, task_id: str, target: str):
    """
    Save agent output into a structured JSON file per target.

    - One file per target
    - Append under task_id
    - UTF-8 safe
    - Deterministic structure
    """

    if not text or not text.strip():
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    safe_target = target.replace(" ", "_").lower()
    file_path = DATA_DIR / f"{safe_target}_{TYPE}_collected_data.json"

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("Input text is not valid JSON")

    if not isinstance(items, list):
        raise ValueError("Expected a list of items")

    # ---- Normalize items into required schema ----
    normalized: List[Dict[str, Any]] = []
    for item in items:
        normalized.append({
            "title": item.get("Title", "").strip(),
            "date": item.get("Date", "").strip(),
            "url": item.get("Source URL", "").strip(),
            "summary": item.get("Initiative Summary", "").strip()
        })

    if file_path.exists():
        with file_path.open("r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = {}
    else:
        existing = {}

    if not existing:
        existing = {
            "target": target,
            "time": now,
            "data": {}
        }

    existing["data"].setdefault(task_id, [])
    existing["data"][task_id].extend(normalized)
    existing["time"] = now

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=4, ensure_ascii=False)


#tavily tools#

from dotenv import load_dotenv
from langchain_tavily import TavilySearch
load_dotenv()

def pretty_print_tavily(results):
    out=[]

    out.append(f"Query: {results.get('query')}\n")

    for i,item in enumerate(results.get("results",[]),1):
        out.append(f"Result {i}:")
        out.append(f"  Title: {item.get('title')}")
        out.append(f"  URL:   {item.get('url')}\n")

        content=item.get("content","").strip()
        if content:
            out.append(f"  Snippet: {content[:300]}...\n")

    if results.get("follow_up_questions"):
        out.append(f"Follow-up questions: {results['follow_up_questions']}\n")

    if results.get("answer"):
        out.append(f"Answer summary: {results['answer']}\n")

    return "\n".join(out)


tool = TavilySearch(
    max_results=5,
    topic="general",
    include_answer=True,
    include_raw_content=False,
    #YYYY-MM-DD
    start_date="2024-10-01",     # only results after this
    end_date="2025-12-30",        # only results before this
    # include_images=False,
    # include_image_descriptions=False,
    # search_depth="basic",
    # time_range="day",
    # include_domains=None
)

def tav_search(query:str)->str:
    """
    Searches query using tavily

    Args:
        query: query to search
    """
    print(f"[AGENT] Tool[tav_search]: query:{query}")
    tool_call=tool.invoke({"query": query})

    return pretty_print_tavily(tool_call)


from langchain_tavily import TavilyExtract

extract_tool = TavilyExtract()

import json
from typing import Optional

def get_page(url: str) -> Optional[str]:
    """
    Given a URL, use TavilyExtract to get page raw content.
    Returns raw content as string or None.
    """
    print(f"[AGENT] Tool[get_page]: url:{url}")

    result = extract_tool.invoke({"urls": [url]})

    # Case 1: Tavily returned JSON as string
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            # Tavily sometimes just returns raw content directly
            return result.strip() or None

    # Case 2: Proper dict response
    if not isinstance(result, dict):
        return None

    results = result.get("results")
    if not results:
        return None

    page_data = results[0]
    return page_data.get("raw_content")

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