t=open("cleaned_metadata.jsonl","a")
import json
with open("metadata.jsonl","r") as f:
    for line in f:
        parsed=json.loads(line.strip())
        flatened_Keywords=",".join(parsed["keywords"])
        cleaned_metadata={
            "keywords":flatened_Keywords,
            "summary":parsed["summary"]
        }
        t.write(json.dumps(cleaned_metadata, ensure_ascii=False) + "\n")
t.close()
