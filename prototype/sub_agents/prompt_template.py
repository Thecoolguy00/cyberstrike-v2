def get_agent_prompt(agent_prompt:str,tool_schema:str,history:str,state):
    prompt =f"""
    RESPONSE SCHEMA (choose exactly one):

    1. NORMAL RESPONSE
    {{
        "thinking": "explain your reasoning step-by-step",
        "message": "natural language reply for the user"
    }}

    2. TOOL CALL
    {{
        "thinking": "explain why a tool call is needed",
        "tool_name": "string tool name",
        "args": {{ "key": value, "key": value }}
    }}

    RULES:
    - Use ONLY one schema per reply.
    - NEVER mix "message" with tool calls.
    - NEVER use a tool if the result is already in the history.
    - NEVER call a tool twice for the same arguments.
    - Respond JSON ONLY.

    {agent_prompt}

    {tool_schema}

    History:
    {history}

    Tools used so far:
    {state["tool_used"]}
    """

    return prompt