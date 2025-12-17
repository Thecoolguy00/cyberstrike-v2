    
# keywords=["hell","angels","heaven","death"]
# summary="This paragraph explains about the concept of life and death"
# meta=",".join(keywords)
# with open("metadata.txt","a") as f:
#     f.write(f"{meta}_{summary}")

# with open("metadata.txt") as f:
#     row_data=f.readline()
#     metadata=[x for x in row_data.split("_")]
#     keys=[y for y in metadata[0].split(",")]
#     print(f"keywords: {keys}, summary: {metadata[1]}")

import json

metadata = {
    "qa_id": 1,
    "keywords": ["PIN reset", "IT Helpdesk", "security question"],
    "summary": "Steps to reset a forgotten PIN via intranet self-service portal."
}

with open("est.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(metadata, ensure_ascii=False) + "\n")

metadata_list = []
with open("metadata.jsonl", encoding="utf-8") as f:
    for line in f:
        metadata_list.append(json.loads(line.strip()))

print(metadata_list[0]["keywords"], metadata_list[0]["summary"])