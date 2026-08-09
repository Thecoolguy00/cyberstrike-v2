"""cat tool: invoke the real Linux `cat` binary on the MCP host.

Used to fetch ExploitDB .txt exploit files returned by searchsploit.
"""

import subprocess
from typing import Optional


def cat_file_action(filepath: str, max_chars: Optional[int] = 20000) -> str:
    """
    Return the contents of a file via the system `cat`, capped at ``max_chars``.
    """
    if not filepath:
        return "error: no filepath provided"
    try:
        result = subprocess.run(
            ["cat", filepath],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return f"error reading {filepath}: {(result.stderr or '').strip()}"
        content = result.stdout or ""
        if max_chars and len(content) > max_chars:
            content = content[:max_chars] + "\n...[truncated]"
        return content
    except FileNotFoundError:
        return "error: 'cat' binary not available on this host"
    except Exception as exc:
        return f"error reading {filepath}: {exc}"