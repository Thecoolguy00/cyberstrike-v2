from pathlib import Path
from prototype.mcp_stuff.background_tasks import launch_background_task
from prototype.mcp_stuff.kali_command import CommandRunner

#change the path to absolute path after moving it to kali
small_wordlist = Path("prototype/mcp_stuff/assets/short.txt")


def feroxbuster_foreground_action(target: str) -> str:
    """Run a foreground feroxbuster scan using the bundled asset wordlist."""
    if not small_wordlist.exists():
        return f"error: wordlist not found: {small_wordlist}"

    command = [
        "feroxbuster",
        "-u",
        target,
        "-w",
        str(small_wordlist),
    ]
    return CommandRunner("feroxbuster", timeout=300).execute(command)

def start_feroxbuster_action(target: str, max_runtime: int = 900) -> dict:
    """
    Start a feroxbuster directory brute-force scan in the background.

    Args:
        target: The URL of the web application to scan
        max_runtime: Maximum runtime in seconds before the task expires

    Returns:
        dict: Task information including task_id, status, output_file, and max_runtime
    """
    wordlist = "/usr/share/wordlists/dirb/common.txt"

    if not Path(wordlist).exists():
        return {
            "error": "wordlist not found",
            "status": "failed"
        }

    # Basic feroxbuster args
    args = ["-u", target, "-w", wordlist]

    task_id, output_file = launch_background_task(cmd="feroxbuster", args=args, max_runtime=max_runtime)

    return {
        "task_id": task_id,
        "status": "started",
        "output_file": str(output_file),
        "max_runtime": max_runtime
    }
