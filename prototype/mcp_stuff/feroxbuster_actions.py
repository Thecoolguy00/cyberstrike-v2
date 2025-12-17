from prototype.mcp_stuff.background_tasks import launch_background_task, wait_for_task
from pathlib import Path
import asyncio

async def run_feroxbuster(
    url: str,
    wordlist: str = "/usr/share/wordlists/dirb/common.txt",
    runtime: int = 120,
    idle_time:int=15,
    poll_interval:int=2
) -> str:
    """
    Launch feroxbuster in background, wait 'runtime' seconds,
    then fetch and return results.
    """
    if not Path(wordlist).exists():
        return "wordlist not found"

    # Basic feroxbuster args
    args = ["-u", url, "-w", wordlist]

    # Launch background task
    task_id, output_file = launch_background_task("feroxbuster", args, max_runtime=runtime)

    print(f"[+] Feroxbuster started (Task ID: {task_id})")
    print(f"    Output file: {output_file}")

    # Wait for it asynchronously
    res = await wait_for_task(task_id, timeout=runtime,idle_time=idle_time,poll_interval=poll_interval)

    # Handle timeout case
    if res is None:
        p = Path(output_file)
        if p.exists():
            try:
                return p.read_text(errors="ignore")
            except Exception:
                return "Timed out and could not read output file"
        return "Timed out and no output available"

    # If task completed
    output_path = Path(res.get("output_file", output_file))
    if output_path.exists():
        try:
            return output_path.read_text(errors="ignore")
        except Exception:
            return "Completed, but failed to read output file"

    return "No output found"

# Standalone runner
if __name__ == "__main__":
    asyncio.run(run_feroxbuster("http://example.com", runtime=120,idle_time=15,poll_interval=2))
