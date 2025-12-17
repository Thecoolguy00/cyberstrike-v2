from langchain.embeddings.base import Embeddings
import requests

class LocalAPIEmbeddings(Embeddings):
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _embed(self, texts):
        payload = {"content": texts}
        res = requests.post(f"{self.base_url}/embedding", json=payload)
        res.raise_for_status()
        data = res.json()
        # Flatten the extra [ ] around the embedding vector
        return [item["embedding"][0] for item in data]

    def embed_documents(self, texts):
        return self._embed(texts)

    def embed_query(self, text):
        return self._embed([text])[0]

embedding=LocalAPIEmbeddings(base_url="http://127.0.0.1:8000")

# print(embedding.embed_query("who are you?"))