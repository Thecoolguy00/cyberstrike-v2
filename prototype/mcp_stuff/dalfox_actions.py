from typing import Optional
from prototype.mcp_stuff.kali_command import CommandRunner
from prototype.mcp_stuff.helper import encode_url_params

class DalCommand(CommandRunner):
    def __init__(self):
        super().__init__("dalfox", timeout=300)

def dalfox_basic_scan_action(target: str) -> str:
    """
    Basic dalfox scan
    For example: dalfox url "http://target.com/" or "http://target.com/?q=blablabla"
    Query parameter values are automatically URL-encoded so XSS payloads
    containing < > pass the command validator.
    """
    cmd = DalCommand()
    safe_target = encode_url_params(target)
    command = [cmd.command_name] + ["url", safe_target]
    return cmd.execute(command)