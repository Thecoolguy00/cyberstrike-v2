from typing import Optional
from prototype.mcp_stuff.kali_command import CommandRunner

class DalCommand(CommandRunner):
    def __init__(self):
        super().__init__("dalfox", timeout=300)

def dalfox_basic_scan_action(target: str) -> str:
    """
    Basic dalfox scan
    For example: dalfox url "http://target.com/" or "http://target.com/?q=blablabla"
    """
    cmd = DalCommand()
    command=[cmd.command_name]+["url",f"{target}"] # targets url with parameter will break if the url is not stringified
    return cmd.execute(command)