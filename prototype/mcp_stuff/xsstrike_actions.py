from typing import Optional
from prototype.mcp_stuff.kali_command import CommandRunner
from prototype.mcp_stuff.helper import encode_url_params

class XssCommand(CommandRunner):
    def __init__(self):
        super().__init__("xsstrike", timeout=300)

def xsstrike_basic_scan_action(target: str) -> str:
    """
    Basic XSStrike scan
    For example: xsstrike -u "https://target.com/"
    Query parameter values are automatically URL-encoded so XSS payloads
    containing < > pass the command validator.
    """
    cmd = XssCommand()
    safe_target = encode_url_params(target)
    command = [cmd.command_name] + ["-u", safe_target]
    return cmd.execute(command)

#xsstrike requires a confirmation after finding a reflection...what to do...

#add option with post xsstrike -u "http://10.49.139.108:5000" --data "comment=asdasd"
#xsstrike -u "http://10.49.139.108:5000" --data "comment=<script>alert(1)</script>" the output shows reflections found...need to test of fresh server