"""Fixed V4 discovery settings."""

METADATA_PATHS = ("robots.txt", "sitemap.xml", "security.txt")
HTTP_PROBE_METHODS = ("GET", "HEAD", "OPTIONS")
DEFAULT_BODY_SIZE = 50_000
DEFAULT_TIMEOUT = 15
DEFAULT_HTTP_TIMEOUT = 5
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_HTTP_REQUESTS = 40
DEFAULT_MAX_JS_FILES = 10
DEFAULT_MAX_FEROX_HITS = 50
DEFAULT_MAX_RUNTIME = 180
DEFAULT_FEROX_WORDLIST = "small"
DEFAULT_FEROX_THREADS = 20
DEFAULT_FEROX_DEPTH = 1
WEB_PORTS = {80: "http", 443: "https", 8000: "http", 8080: "http", 8443: "https"}
# Skip clear, well-known non-HTTP services. Unknown/custom ports remain
# eligible because their service banner may be misleading or incomplete.
NON_HTTP_PORTS = {
    21, 22, 23, 25, 53, 69, 110, 111, 123, 135, 137, 138, 139, 143,
    161, 389, 445, 514, 515, 631, 993, 995, 1433, 1521, 2049, 3306,
    3389, 5432, 5900, 6379, 27017,
}

# Planner / attack-session loop caps
MAX_DECISION_ITERATIONS = 8
MAX_ATTACK_SESSION_ITERATIONS = 8
MAX_STUCK_CYCLES = 3

# Phase label the agent sub-layer recognizes for active testing tasks. The ver3
# agents only accept recon / enumeration / vuln_analysis / exploitation, so V4
# attack & intel tasks must prefix with "[vuln_analysis]" to pass their phase lock.
AGENT_TASK_PHASE_PREFIX = "[vuln_analysis]"
