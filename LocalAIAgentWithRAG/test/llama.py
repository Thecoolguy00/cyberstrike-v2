import requests

session = requests.Session()

session.headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
}

# health = session.request(
#     method='get',
#     url="http://localhost:8000/health")

# print(health.text)

payload = {
    'content': ['what is my name?','how are you?']
}

response =  session.request(
    method='post', 
    url='http://localhost:8000/embedding',        
    json=payload)

import json
data = json.loads(response.text)
# vec = data[0]["embedding"][0]
# print(vec,len(vec))
print("done")

#           a little slower than local.py..why?