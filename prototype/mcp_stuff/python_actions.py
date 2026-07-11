import os
import subprocess
import tempfile
import textwrap
import sys

#TODO currently no safety check for code, we'll do it later
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
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass