from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
import os
import pandas as pd
from custom_embedding import LocalAPIEmbeddings

df = pd.read_csv("realistic_restaurant_reviews.csv")
#embeddings = OllamaEmbeddings(model="qwen3-embedding:0.6b",base_url="http://127.0.0.1:11434/")

embeddings=LocalAPIEmbeddings(base_url="http://127.0.0.1:8000")

db_location = "./chrome_langchain_db"
add_documents = not os.path.exists(db_location)

if add_documents:
    documents = []
    ids = []
    
    for i, row in df.iterrows():
        document = Document(
            page_content=row["Title"] + " " + row["Review"],
            metadata={"rating": row["Rating"], "date": row["Date"]},
            id=str(i)
        )
        ids.append(str(i))
        documents.append(document)
        
vector_store = Chroma(
    collection_name="restaurant_reviews",
    persist_directory=db_location,
    embedding_function=embeddings
)

if add_documents:
    vector_store.add_documents(documents=documents, ids=ids)
    
retriever = vector_store.as_retriever(
    search_kwargs={"k": 5}
)

# embedded_query = embeddings.embed_query("What was the name mentioned in the conversation?")
# print(embedded_query,len(embedded_query))
query="types of pizzas the restaurant offers"
print(f"query:{query}")
print(retriever.invoke(query))