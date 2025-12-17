from __future__ import annotations
import shlex
import subprocess
from typing import List, Optional, Sequence, Union
from prototype.mcp_stuff.validators import validate_command

StrSeq = Sequence[str]
CmdArg = Union[StrSeq, str]

class CommandRunner:
    """Base class for executing kali commands"""

    def __init__(self, command_name: str, timeout: int = 200):
        self.command_name = command_name
        self.timeout = timeout

    def run_cmd(self, cmd: CmdArg, timeout: Optional[int] = None) -> str:
        """Safe stateless command runner. cmd is list or string."""
        if isinstance(cmd, str):
            cmd_list = shlex.split(cmd)
        else:
            cmd_list = list(map(str, cmd))

        if timeout is None:
            timeout = self.timeout
        
        #command validation
        if not validate_command(cmd_list):
            return "command illegal or not allowed"

        try:
            proc = subprocess.run(
                cmd_list,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                encoding="utf-8"
            )
        except subprocess.TimeoutExpired as e:
            return f"timeout: {e}"
        except Exception as e:
            return f"error: {e}"

        out = proc.stdout or ""
        err = proc.stderr or ""
        return out + err

    def port_args(self, ports: Optional[Sequence[Union[int, str]]]) -> List[str]:
        """Return ['-p', '22,80'] if ports present, else []"""
        if not ports:
            return []
        return ["-p", ",".join(map(str, ports))]

    def execute(self, command: CmdArg, timeout: Optional[int] = None) -> str:
        return self.run_cmd(command, timeout=timeout)
