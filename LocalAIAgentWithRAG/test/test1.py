from langchain_community.embeddings import LlamaCppEmbeddings

llama = LlamaCppEmbeddings(model_path="D:\Temp\models\embedding models\Qwen3-Embedding-0.6B-f16.gguf",verbose=False)

text = ["This is a test document.","how are you?"]

t1="how are you"
# query_result = llama.embed_documents(text)  
query_result=llama.embed_query(t1)
print(query_result)

#                   fails in batch, maybe qwen3-embeddings doesn't support batch embedding
#                   works, a little slower than ./local.py
#                   I think I'll be fine if I just made a custom lllama.cpp server function, which only should return a single embeeding as a list