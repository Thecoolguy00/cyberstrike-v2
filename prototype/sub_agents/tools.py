import subprocess
import tempfile
import textwrap
import sys


def execute_python(code: str, timeout=15):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(textwrap.dedent(code))
        path = f.name

    try:
        proc = subprocess.run(
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
    

#helper function for execute_python
def extract_python_code(llm_output: str) -> str:
    if "```python" in llm_output:
        return llm_output.split("```python")[1].split("```")[0].strip()
    raise ValueError("No python code block found")
