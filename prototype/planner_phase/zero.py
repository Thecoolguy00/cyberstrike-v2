PHASES = [
  "RECON",
  "ENUMERATION",
  "VULN_CONFIRMATION",
  "EXPLOITATION",
  "POST_EXPLOIT",
  "REPORT"
]

PHASE_CONFIG = {
  "RECON": {
    "allowed_agents": ["nmap_a", "curl_a"],
    "exit_conditions": ["ports_known","server identified"]
  },
  "ENUMERATION": {
    "allowed_agents": ["ferox_a", "curl_a"],
    "exit_conditions": ["inputs_or_paths_known"]
  },
  "VULN_CONFIRMATION": {
    "allowed_agents": ["xss_a", "python_a"],
    "exit_conditions": ["vuln_confirmed", "inputs_exhausted"]
  },
  "EXPLOITATION": {
    "allowed_agents": ["python_a"],
    "exit_conditions": ["access_gained", "exploit_failed"]
  },
  "POST_EXPLOIT": {
    "allowed_agents": ["python_a"],
    "exit_conditions": ["data_collected"]
  },
  "REPORT": {
    "allowed_agents": [],
    "exit_conditions": []
  }
}

