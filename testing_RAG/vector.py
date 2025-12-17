from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
import os
import pandas as pd
from custom_embedding import LocalAPIEmbeddings
import json

df = pd.read_csv("synthetic_knowledge_items.csv")
embeddings = OllamaEmbeddings(model="qwen3-embedding:0.6b",base_url="http://127.0.0.1:11434/")

#embeddings=LocalAPIEmbeddings(base_url="http://127.0.0.1:8000")

db_location = "./helpdesk_db"
add_documents = not os.path.exists(db_location)


#list of metadata
metadata_list = []
with open("cleaned_metadata.jsonl", encoding="utf-8") as f:
    for line in f:
        metadata_list.append(json.loads(line.strip()))

#max_chonking
from langchain.text_splitter import RecursiveCharacterTextSplitter
splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)

if add_documents:
    documents = []
    ids = []

    for qa_id, row in df.iterrows():
        question=row["question"]
        answer=row["answer"]
        chunks = splitter.split_text(answer)

        for chunk_index, chunk in enumerate(chunks):
            unique_id = f"{qa_id}_{chunk_index}"
            document = Document(
                page_content=chunk,
                metadata={"keywords":metadata_list[qa_id]["keywords"],"question":question,"qa_id":qa_id,"chunk_index":chunk_index,"summary":metadata_list[qa_id]["summary"]},
            )
            ids.append(str(unique_id))
            documents.append(document)
        
vector_store = Chroma(
    collection_name="tech_helpdesk",
    persist_directory=db_location,
    embedding_function=embeddings
)


if add_documents:
    print(f"Total documents prepared: {len(documents)}")
    vector_store.add_documents(documents=documents, ids=ids)
    
retriever = vector_store.as_retriever(
    search_kwargs={"k": 5}
)


#test

# embedded_query = embeddings.embed_query("How to backup files?")
# print(embedded_query)

# query="fixing Jammed printer"
# print(f"query: {query} \n Retrieved chunks using retrevier:{retriever.invoke(query)}")

# results = vector_store.similarity_search_with_score(
#     query, k=1
# )
# for res, score in results:
#     print("----------------------------------------")
#     print(f"Similarity Search: * [SIM={score:3f}] {res.page_content} [{res.metadata}]")

#           formatting metadata

question="how to connect to a company server"

relevant_data = retriever.invoke(question)

# grouped = {}
# for doc in relevant_data:
#     qid = doc.metadata['qa_id']
#     if qid not in grouped:
#         grouped[qid] = {
#             'qa_id': qid,
#             'summary': doc.metadata.get('summary', ''),
#             'content': []
#         }
#     grouped[qid]['content'].append(doc.page_content)

# # Convert content lists to one string
# for qid in grouped:
#     grouped[qid]['content'] = "\n\n".join(grouped[qid]['content'])

# # Now sorted by score or number of chunks merged
# results = list(grouped.values())
# # print(results)

best_res_id=relevant_data[0].metadata["qa_id"]

best = vector_store.get(where={"qa_id": best_res_id})

docs = best["documents"]
metas = best["metadatas"]

# Sort docs by chunk_index
order = sorted(range(len(metas)), key=lambda i: metas[i]["chunk_index"])
ordered_docs = [docs[i] for i in order]

# Combine and split into lines
lines = "\n".join(ordered_docs).split("\n")

seen = set()
cleaned_lines = []
for line in lines:
    if line.strip() not in seen:
        cleaned_lines.append(line)
        seen.add(line.strip())

combined = "\n".join(cleaned_lines)
lissss=["asdasd","asdsadasdasd"]
lissss.append(combined)
print(lissss[-1])

