from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

llm = ChatOpenAI(
    model="qwen-local",
    openai_api_base="http://127.0.0.1:8080/v1",
    openai_api_key="none",
    temperature=0
)

import json, re
import pandas as pd

df = pd.read_csv("synthetic_knowledge_items.csv")
f=open("metadata.jsonl","a",encoding="utf-8")

for i, row in df.iterrows():
    answer=row["answer"]
    metadata_prompt = f"""
    Generate metadata for the following text. 
    Only Return in JSON format:

    - keywords: list of relevant keywords
    - summary: a few words short summary

    Text: '''{answer}'''
    """

    response = llm.invoke([HumanMessage(content=metadata_prompt)])

    #pre-processing the output of llm
    res=response.content.strip()
    res = res.replace("```json", "").replace("```", "").strip()
    try:
        parsed_metadata = json.loads(res)
    except json.JSONDecodeError:
        # fallback if model adds text around JSON
        match = re.search(r'\{.*\}', res, re.S)
        if match:
            parsed_metadata = json.loads(match.group(0))
        else:
            raise ValueError(f"Invalid JSON returned:\n{res}")
        
    f.write(json.dumps(parsed_metadata, ensure_ascii=False) + "\n")

f.close()
print("metadata generation completed")


#               implement a keyword search then sematic seaarch(vector search), also reranker