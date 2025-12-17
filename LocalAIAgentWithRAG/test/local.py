import requests, json

data = {"content": ["Unauthorized login attempt detected.","hi, how are you?"]}
r = requests.post("http://127.0.0.1:8000/embedding", json=data)

# print(r.json()[0]["embedding"][0])
# print(r.json()[1]["embedding"][0])
# print("done")
print(r.json())

#                           works, I think fastest one, because using qwen3 FP16 on GPU, RTX 3050 GPU natively supports FP16, fast with high accuracy
#                           supports, batch embedding
#                           how to build a wraper for chromaDB...embed_query() and embed_document(), done-custom_embedding