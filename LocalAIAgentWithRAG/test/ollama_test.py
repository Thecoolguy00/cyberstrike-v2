from langchain_ollama import OllamaEmbeddings

embedding=OllamaEmbeddings(model="qwen3-embedding:0.6b",base_url="http://127.0.0.1:11434/")

print(embedding.embed_query("who are you?"))

