"""Small, tolerant Nmap text parser."""

import re
from typing import Any, Dict, List


PORT_RE = re.compile(r"(?P<port>\d+)/(?:tcp|udp)\s+(?P<state>\S+)\s+(?P<service>\S+)(?:\s+(?P<version>.*))?", re.I)


def parse_nmap(output: str) -> List[Dict[str, Any]]:
    ports = []
    for line in output.splitlines():
        match = PORT_RE.search(line.strip())
        if not match:
            continue
        data = match.groupdict()
        ports.append({
            "port": int(data["port"]),
            "protocol": "tcp" if "/tcp" in line.lower() else "udp",
            "state": data["state"],
            "service": data["service"],
            "version": (data.get("version") or "").strip(),
        })
    return ports
