from langchain_core.messages import AIMessage
import json, random

def response_route_multi(msg):
    json_str = extract_json_block(msg.content)
    con = json.loads(json_str)

    tool_calls = con.get("tool_calls", [])
    if not tool_calls:
        return {"messages": [msg], "tool_used": []}

    out_msgs = []
    used = []

    for call in tool_calls:
        name = call["tool_name"]
        args = call["args"]
        uid = f"{name}{random.randint(0,9999)}"

        m = AIMessage(
            content="",
            additional_kwargs={
                "tool_calls": [{
                    "id": uid,
                    "function": {"name": name, "arguments": json.dumps(args)},
                    "type": "function"
                }]
            },
            tool_calls=[{
                "name": name,
                "args": args,
                "id": uid,
                "type": "tool_call"
            }]
        )

        out_msgs.append(m)
        used.append(name)

    return {"messages": out_msgs, "tool_used": used}
