import subprocess
import tempfile
import textwrap
import sys
import asyncio


def execute_python(code: str, timeout=15):
    """Executes python code"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(textwrap.dedent(code))
        path = f.name

    try:
        proc = subprocess.run(
            #sys.executable returns the python path for the current environment, ensures code runs in main process python environment
            [sys.executable, path],
            capture_output=True,
            text=True,
            timeout=timeout
        )

        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "Execution timed out"
        }
    

def extract_python_code(llm_output: str) -> str:
    """for python, extracts code from markdown"""
    if "```python" in llm_output:
        return llm_output.split("```python")[1].split("```")[0].strip()
    raise ValueError("No python code block found")


async def wait_for(minutes: float) -> str:
    """
    Wait/sleep for a specified duration in minutes (between 1.0 and 6.0 minutes).
    Useful to wait for background tasks/scans to progress.

    Args:
        minutes (float): The number of minutes to wait (between 1.0 and 6.0).
    """
    clamped_minutes = max(1.0, min(6.0, minutes))
    seconds = clamped_minutes * 60.0
    print(f"[wait_for] Sleeping for {clamped_minutes} minutes ({seconds} seconds)...")
    await asyncio.sleep(seconds)
    return f"Successfully waited/slept for {clamped_minutes} minutes."