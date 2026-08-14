"""Feroxbuster output parser."""

import re
from typing import Any, Dict, List


URL_RE = re.compile(r"(?P<url>https?://\S+)")
STATUS_RE = re.compile(r"(?:Status|status):?\s*(?P<status>\d{3})", re.I)
SIZE_RE = re.compile(r"(?:Size|size):?\s*(?P<size>\d+)", re.I)


def parse_ferox(output: str) -> List[Dict[str, Any]]:
    hits = []
    for line in output.splitlines():
        url_match = URL_RE.search(line)
        if not url_match:
            continue
        status_match = STATUS_RE.search(line)
        size_match = SIZE_RE.search(line)
        hits.append({
            "url": url_match.group("url").rstrip(".,"),
            "status": int(status_match.group("status")) if status_match else None,
            "size": int(size_match.group("size")) if size_match else None,
        })
    return hits
