# Cyberstrike v2: Automated WAPT Orchestrator

Cyberstrike v2 is a modular, multi-agent Web Application Penetration Testing (WAPT) framework built on LangChain and LangGraph. It automates security assessments using an iterative strategic-tactical loop with parallel task execution and active vulnerability nudging.

---

## Architecture and Core Loop

The framework coordinates high-level phase management with low-level tool execution:

1. **Strategic Planner (`strategic_planner_module.py`)**
   Decides the current phase (recon, enumeration, vuln_analysis, exploitation, reporting) and sets a high-level phase objective based on target knowledge.

2. **Vulnerability Advisor (`vuln_advisor.py`)**
   Analyzes the knowledge graph every cycle to emit a `VulnNudge` (priority: high, medium, skip) to prompt the tactical planner toward high-value, unchecked attack vectors.

3. **Tactical Planner (`tactical_planner_module.py`)**
   Generates a batch of concrete tasks for available agents, specifying task dependencies (`task_id` and `depends_on`) to allow parallel execution.

4. **Parallel Executor (`executor.py`)**
   Executes tasks in concurrent batches (using `asyncio.gather`) respecting dependencies.

5. **Knowledge Graph (`schemas.py`)**
   Deduplicates and merges structured findings (open ports, web services, endpoints, input points, findings, notes) across cycles.

---

## Execution Flow and Lifecycle

The graph loops between the components as shown in the lifecycle diagram below:

```text
START
  │
  ▼
strategic          - decides phase + objective, runs ONCE per phase
  │
  ▼
vuln_advisor       - reads knowledge graph, emits nudge (high/medium/skip)
  │                   runs for ALL phases including recon + enumeration
  │ (reporting phase -> merge_knowledge directly)
  ▼
tactical           - generates BATCH of tasks (parallel-tagged)
  │                   HIGH nudge = must include at least one nudge task
  │                   injects nudge as visible banner in prompt
  │
  ├─ empty plan ──► merge_knowledge -> strategic  (phase done)
  │
  ▼
execute            - runs ready layer 1 concurrently, then layer 2, etc.
  │                   nmap + curl run at the same time if no dependency
  │
  ▼
vuln_advisor       - re-reads updated knowledge graph, picks next nudge
  │                   (previous results now visible -> better decisions)
  ▼
tactical           - next cycle with fresh nudge
  │
  └── loop ──────────────────────────────────────────────────────┘
```

### Cycle Examples

**Cycle 1:**
- **advisor -> nudge:** `robots_check` (high) - "check /robots.txt on port 80"
- **tactical -> plan:**
  - `task_id="nmap_quick"`, `depends_on=[]`, `agent=nmap_a`
  - `task_id="curl_robots"`, `depends_on=[]`, `agent=curl_a` (nudge task)
  - `task_id="curl_headers"`, `depends_on=[]`, `agent=curl_a`
- **execute:** `nmap_quick`, `curl_robots`, and `curl_headers` run in parallel.

**Cycle 2:**
- **advisor -> nudge:** `git_exposure` (high) - nmap revealed port 80 Apache
- **tactical -> plan:**
  - `task_id="nmap_full"`, `depends_on=["nmap_quick"]`, `agent=nmap_a`
  - `task_id="curl_git"`, `depends_on=[]`, `agent=curl_a` (nudge task)
  - `task_id="curl_env"`, `depends_on=[]`, `agent=curl_a`
- **execute:** `curl_git` and `curl_env` run in parallel immediately; `nmap_full` waits for `nmap_quick` to finish.

A phase finishes when the tactical planner returns an empty plan.

---

## Directory Structure

```text
├── prototype/
│   ├── mcp_stuff/                   # MCP servers and background process utilities
│   │   ├── background_tasks.py      # Non-blocking background process manager
│   │   ├── combined_mcp_server.py   # Aggregated MCP tools endpoint
│   │   └── validators.py            # Safety checks for commands and paths
│   │
│   └── sub_agents/                  # Core orchestration and sub-agent subgraphs
│       ├── master_graph.py          # Orchestration state graph
│       ├── strategic_planner_module.py # High-level phase manager
│       ├── vuln_advisor.py          # Breadth-first vulnerability advisor
│       ├── tactical_planner_module.py  # Dependency-aware task generator
│       ├── executor.py              # Parallel task execution engine
│       ├── schemas.py               # State and Pydantic schemas
│       ├── curl_graph_test_mcp.py   # HTTP analysis agent
│       ├── ferox_graph_test_mcp.py  # Directory/file enumeration agent
│       ├── nmap_graph_test_mcp.py   # Port/service scanning agent
│       ├── python_req_graph_test_mcp.py # Script execution agent
│       └── xss_graph_test_mcp.py    # XSS vulnerability validation agent
│
└── app/                             # Shared utilities, configuration, and logging
```

---

## Getting Started

1. Set up environment variables in a `.env` file (e.g. API keys, base URLs).
2. Configure models in `app/resources/constants.yaml`.
3. Run the orchestrator:
   ```bash
   python -m prototype.sub_agents.master_graph
   ```
