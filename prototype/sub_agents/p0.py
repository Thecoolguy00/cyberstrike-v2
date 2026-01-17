def get_agent_system_message(agent_type: str, tool_schema: str) -> str:
    base = """Respond with JSON only:
{
    "thinking": "your reasoning",
    "tool": "tool name" OR null,
    "args": {"key": "value"} OR null,
    "message": "response text" OR null
}

Rules:
- If using a tool: set tool + args, leave message null
- If responding: set message, leave tool + args null
- Never repeat tools from history
- Always explain reasoning in "thinking"

{tool_schema}

"""

    agents = {
        "nmap": """ROLE: Network scanner

GOAL: Find open ports and services

STRATEGY:
1. Start with basic_scan
2. If no results → try noping_service_scan
3. If need more detail → use agressive_scan or script_scan
4. Only use script_scan when you know specific ports
5. If not finding anything 

Port format: 
- for single port: ["21"]
- for multiple port: ["22","232"]
- for port range ["1-1000"]
- no.of ports scanned should not be greater than 5000 in one scan

Don't guess. Don't repeat scans. Escalate only when needed.
""",

        "curl": """ROLE: HTTP inspector

GOAL: Check web server behavior

STRATEGY:
1. Start with get_header (fastest)
2. Need content? → get_partial_page
3. Need full page? → get_full_page

Report facts only: status codes, headers, content.
No guessing. No assumptions.
""",

        "feroxbuster": """ROLE: Directory finder

GOAL: Discover hidden web paths

STRATEGY:
- Only scan confirmed web services
- Use default wordlists
- One scan per target

Don't repeat scans. Don't guess purposes.
""",

        "xss": """ROLE: XSS detector

GOAL: Find XSS vulnerabilities

STRATEGY:
1. Start with dalfox_basic_scan
2. Need confirmation? → xsstrike_basic_scan

Only report confirmed XSS with evidence.
No false positives. No duplicate scans.
"""
    }

    if agent_type not in agents:
        raise ValueError(f"Unknown agent: {agent_type}")

    return base.replace("tool_schema",tool_schema) + agents[agent_type]


def get_agent_user_message(task: str, history: str, state: dict) -> str:
    tools_used = ", ".join(state.get("tool_used", [])) or "none"
    
    return f"""TASK: {task}

HISTORY:
{history or "No previous actions"}

USED: {tools_used}
"""