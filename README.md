# Cyberstrike v2: Automated WAPT Orchestrator

Cyberstrike v2 is a modular, multi-agent Web Application Penetration Testing (WAPT) framework built on LangChain and LangGraph. It automates security assessments using an iterative strategic-tactical loop with parallel task execution, active vulnerability nudging, and strict phase-based gating.

---

## Architectural Overview & Design Philosophy

The orchestration architecture of Cyberstrike v2 decouples high-level strategic reasoning from low-level tool execution and validation. This is achieved via a multi-layered agent model orchestrated by LangGraph:

1. **Phase-Based Progression**: The pentest executes across distinct phases defined in [schemas.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/schemas.py): `recon` ➔ `enumeration` ➔ `vuln_analysis` ➔ `exploitation` ➔ `reporting`.
2. **Cognitive Task Separation**: Separation of concerns is enforced between planners, extractors, and executors. For instance, the tactical layer is split into distinct planning and extraction nodes so the planning model is not polluted with raw tool parser output.
3. **Parallel Dependency-Aware Execution**: Independent tasks are batched and executed concurrently to optimize time, respecting strict dependency constraints.
4. **Targeted Active Nudging**: A dedicated Vulnerability Advisor runs after every execution cycle to nudge the tactical planner toward high-value, unexplored attack surfaces.

---

## StateGraph Flow and Lifecycle

The orchestration lifecycle is managed in [master_graph.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/master_graph.py). Below is the precise node execution and conditional routing flow:

```text
                  START
                    │
                    ▼
            [ strategic node ] <──────────────────────────────────────┐
                    │                                                 │
            route_after_strategic                                     │
                    │                                                 │
                    ├───────────► [ END ]                             │
                    │                                                 │
                    ▼                                                 │
          [ tactical_planner ] <─────────────────────────┐            │
                    │                                    │            │
           route_after_tactical                          │            │
                    │                                    │            │
                    ├─────────── empty plan ─────────────┼────────┐   │
                    │                                    │        │   │
                    ▼ (non-empty plan)                   │        │   │
              [ execute ]                                │        │   │
                    │                                    │        │   │
                    ▼                                    │        │   │
          [ tactical_extractor ]                         │        │   │
                    │                                    │        │   │
                    ▼                                    │        │   │
             [ vuln_advisor ]                            │        │   │
                    │                                    │        │   │
            route_after_advisor                          │        │   │
                    │                                    │        │   │
                    ├─────────── (non-reporting phase) ──┘        │   │
                    │                                             │   │
                    ▼ (reporting phase)                           │   │
                    │                                             ▼   │
                    └───────────────────────────────────► [ merge_knowledge ]
```

### Flow Walkthrough

1. **Strategic Selection**: [strategic_planner](file:///d:/Temp/langchain-academy/prototype/sub_agents/strategic_planner_module.py#L215-L270) evaluates the overall knowledge graph and sets the `current_phase` and `phase_objective`. If reporting has finished, the graph routes to `END`.
2. **Tactical Planning**: [tactical_planner](file:///d:/Temp/langchain-academy/prototype/sub_agents/tactical_planner_module.py#L545-L607) consumes the phase objective, previous execution history, and active advisor nudges to generate a batch of ready-to-run tasks.
3. **Execution**: [execute_plan](file:///d:/Temp/langchain-academy/prototype/sub_agents/executor.py#L125-L130) runs the ready tasks concurrently via specialized sub-agents.
4. **Structured Extraction**: [tactical_extractor](file:///d:/Temp/langchain-academy/prototype/sub_agents/tactical_planner_module.py#L454-L543) processes raw execution output, extracting *only new* findings to avoid duplicating existing knowledge, and buffers them in `_extracted_knowledge`.
5. **Nudging**: [vuln_advisor](file:///d:/Temp/langchain-academy/prototype/sub_agents/vuln_advisor.py#L226-L257) analyzes the updated target knowledge and registers high-priority vulnerability nudges before looping back.
6. **Merging**: When the tactical plan is empty (phase complete), [merge_knowledge_node](file:///d:/Temp/langchain-academy/prototype/sub_agents/master_graph.py#L68-L103) commits the buffered findings into the master `knowledge` base and returns to the strategic planner to transition phases.

---

## Core Components and Modules

### 1. Master State & Knowledge Graph
- **State Definition**: The orchestrator State is defined by [MasterState](file:///d:/Temp/langchain-academy/prototype/sub_agents/schemas.py#L227-L257) in [schemas.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/schemas.py). It aggregates query data, current phase statistics, execution history, plan tasks, advisor nudges, and accumulated findings.
- **Knowledge Schema**: [TargetKnowledge](file:///d:/Temp/langchain-academy/prototype/sub_agents/schemas.py#L70-L79) models structured target data:
  - `open_ports`: Discovered open TCP/UDP ports and banners.
  - `web_services`: HTTP/HTTPS endpoints, tech stacks, headers, and page titles.
  - `endpoints`: Discovered URLs and paths.
  - `input_points`: Form fields, query parameters, and HTTP methods.
  - `findings`: Confirmed vulnerabilities.
  - `known_cves`: Known CVE data populated during exploit intelligence lookups.
  - `notes`: General text annotations.
- **Deduplication**: Deduplication and incremental updates are handled by [merge_knowledge](file:///d:/Temp/langchain-academy/prototype/sub_agents/schemas.py#L92-L179).

### 2. Strategic Planner
Implemented in [strategic_planner_module.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/strategic_planner_module.py).
- **Function**: [strategic_planner](file:///d:/Temp/langchain-academy/prototype/sub_agents/strategic_planner_module.py#L215-L270)
- **Role**: Evaluates the global target knowledge and directs the orchestrator to advance, loop back, skip, or stay in a phase.
- **Reporting**: In the `reporting` phase, synthesizes all accumulated findings into a structured, executive-ready Penetration Test Report Markdown artifact. In case of LLM failure, a fallback reporter creates an emergency report.

### 3. Tactical Layer (Planner & Extractor)
Implemented in [tactical_planner_module.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/tactical_planner_module.py).
- **Separation of Concerns**: Split into [tactical_extractor](file:///d:/Temp/langchain-academy/prototype/sub_agents/tactical_planner_module.py#L454-L543) (extraction only) and [tactical_planner](file:///d:/Temp/langchain-academy/prototype/sub_agents/tactical_planner_module.py#L545-L607) (planning only).
- **Phase Playbooks**: Enforces strictly defined phase behaviors:
  - `recon`: Service and port discovery. Strictly forbids injection testing or brute-forcing.
  - `enumeration`: Directory/endpoint mapping. Strictly forbids injection testing or service fingerprinting.
  - `vuln_analysis`: Targeted vulnerability probing.
  - `exploitation`: Constructing proof-of-concepts to confirm vulnerabilities.
- **Dependency Chains**: Outputs [Task](file:///d:/Temp/langchain-academy/prototype/sub_agents/schemas.py#L260-L266) models with `task_id` and `depends_on` lists.

### 4. Vulnerability Advisor
Implemented in [vuln_advisor.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/vuln_advisor.py).
- **Function**: [vuln_advisor](file:///d:/Temp/langchain-academy/prototype/sub_agents/vuln_advisor.py#L226-L257)
- **Role**: Emits a [VulnNudge](file:///d:/Temp/langchain-academy/prototype/sub_agents/schemas.py#L196-L212) specifying an attack class and specific targets.
- **Advisor Categories**: Evaluates vulnerabilities in a prioritized queue:
  1. `USER_INTENT_DRIFT` (Validates if target vulnerability request was ignored).
  2. `INPUT_CLASS_UNCHECKED` (Unchecked query/POST parameters).
  3. `IDOR_UNCHECKED` (Numeric IDs in paths/params).
  4. `API_SECRET_LEAK` (Page sources & JS file scanning).
  5. `SERVICE_EXPLOIT_INTEL` (Exploit intelligence checks).
  6. `DIRECTORY_LISTING` (Exposed directories).
  7. `CLICKJACKING_UNCHECKED` (Lack of frame security headers).
- **Phase Gates**: Enforces a strict whitelist restricting nudges to permitted categories depending on the active phase (e.g. only `SERVICE_EXPLOIT_INTEL` in `recon`).

### 5. Parallel Executor
Implemented in [executor.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/executor.py).
- **Function**: [execute_plan](file:///d:/Temp/langchain-academy/prototype/sub_agents/executor.py#L125-L130)
- **Role**: Evaluates the plan, determines tasks with satisfied dependencies (the "ready" layer), and launches them concurrently using `asyncio.gather`.
- **Agents**: Maps task execution requests to specialized sub-agent graphs.

---

## Sub-Agent Subgraphs

Specialized agent graphs are defined under [prototype/sub_agents/](file:///d:/Temp/langchain-academy/prototype/sub_agents/):

- **nmap_a** ([nmap_graph_test_mcp.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/nmap_graph_test_mcp.py)): Orchestrates port discovery, OS fingerprinting, and service detection.
- **http_a** ([http_graph.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/http_graph.py)): Handles complex HTTP requests using custom presets, redirects, and headers.
- **ferox_a** ([ferox_graph_test_mcp.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/ferox_graph_test_mcp.py)): Brute-forces directories and files using wordlists.
- **python_a** ([python_req_graph_test_mcp.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/python_req_graph_test_mcp.py)): Compiles and runs custom Python scripts to test custom/complex vectors.
- **xss_a** ([xss_graph_test_mcp.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/xss_graph_test_mcp.py)): Probes for Cross-Site Scripting (XSS) injection.
- **intel_a** ([exploit_intel_graph.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/exploit_intel_graph.py)): Searches databases and search engines for known PoCs and vulnerabilities. Uses helper APIs defined in [tools.py](file:///d:/Temp/langchain-academy/prototype/sub_agents/tools.py) (NVD API, Tavily, GitHub API).

---

## Model Context Protocol (MCP) Tool Integration

The framework leverages MCP to execute low-level operating system commands and tools in a safe, decoupled environment.

### MCP Server
Defined in [combined_mcp_server.py](file:///d:/Temp/langchain-academy/prototype/mcp_stuff/combined_mcp_server.py).
- Starts a FastMCP server running over Streamable HTTP on port 4545.
- Exposes tools like:
  - `basic_scan`, `aggressive_scan`, `noping_version_scan`, `script_scan` (wrapping nmap)
  - `http_request` (wrapping httpx)
  - `dalfox_basic_scan` (wrapping DalFox XSS scanner)
  - `xsstrike_basic_scan` (wrapping XSStrike XSS scanner)
  - `start_nmap_long_scan`, `start_feroxbuster` (wrapping background execution)
  - `exe_cute_python` (wrapping isolated python code runner)
  - `searchsploit_search` (wrapping ExploitDB search)

### Security Gating & Sanitization
Defined in [validators.py](file:///d:/Temp/langchain-academy/prototype/mcp_stuff/validators.py).
- The function [validate_command](file:///d:/Temp/langchain-academy/prototype/mcp_stuff/validators.py#L211-L224) serves as a gate for command validation.
- Sanitizes targets, URLs, port ranges, and checks for shell chaining and command injection vectors via regexes and blacklist checks.

### Background Task Management
Defined in [background_tasks.py](file:///d:/Temp/langchain-academy/prototype/mcp_stuff/background_tasks.py).
- Manages long-running processes (e.g. feroxbuster, port scans) asynchronously.
- Exposes task status check and output acquisition interfaces.

---

## Directory Structure

```text
├── prototype/
│   ├── mcp_stuff/                           # MCP server tool wrapper actions
│   │   ├── background_tasks.py              # Long-running background process manager
│   │   ├── combined_mcp_server.py           # Startable FastMCP Streamable-HTTP tool server
│   │   ├── validators.py                    # Input command sanitation and safety validators
│   │   ├── kali_command.py                  # Direct OS command runner helper
│   │   ├── helper.py                        # MCP helpers
│   │   └── *_actions.py                     # Tool specific actions (nmap, HTTP, XSS, feroxbuster, etc.)
│   │
│   └── sub_agents/                          # Multi-agent orchestrator graphs
│       ├── master_graph.py                  # Core LangGraph orchestration & lifecycle loops
│       ├── strategic_planner_module.py      # High-level phase progression & reporting manager
│       ├── tactical_planner_module.py       # Separated planner and extractor logic
│       ├── vuln_advisor.py                  # Active vulnerability nudger and phase gates
│       ├── executor.py                      # Parallel task scheduler and dependency resolver
│       ├── schemas.py                       # Master and tactical schemas and deduplicating merge logic
│       ├── tools.py                         # Sub-agent helper tools (NVD, GitHub PoC, Tavily search)
│       ├── schema_validator.py              # Pydantic LLM output shape validator
│       ├── true_mcp_exec.py                 # Streamable HTTP MCP client execution layer
│       ├── prompt.py                        # Common prompts for sub-agent graphs
│       └── *_graph.py / *_graph_test_mcp.py # Individual agent subgraphs (nmap, HTTP, XSS, etc.)
│
└── app/                                     # Configuration, shared utilities, logging and constants
```

---

## Getting Started

### Prerequisites

1. Install system dependencies (e.g., `nmap`, `feroxbuster`, `dalfox`, `xsstrike` must be installed on the host OS / Kali instance).
2. Install Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables in a `.env` file in the workspace root:
   ```env
   TAVILY_API_KEY=your_tavily_key
   MCP_BASE_URL=http://localhost:4545/mcp
   # Add any required model API keys (OpenAI, Anthropic, etc.)
   ```

### Execution Steps

1. **Start the MCP Tool Server**:
   ```bash
   python -m prototype.mcp_stuff.combined_mcp_server
   ```
2. **Launch the WAPT Orchestrator**:
   ```bash
   python -m prototype.sub_agents.master_graph
   ```
