from typing import Optional
from prototype.mcp_stuff.kali_command import CommandRunner

class NmapCommand(CommandRunner):
    def __init__(self):
        super().__init__("nmap", timeout=300)

def basic_scan_action(target: str) -> str:
    """
    Basic scan
    For example: nmap 192.168.1.1
    """
    cmd = NmapCommand()
    return cmd.execute([cmd.command_name, target])

def aggressive_scan_action(target: str, ports: Optional[list[str]] = None) -> str:
    """
    Intense scan (-T4 -A)
    Includes: OS detection, version detection, script scanning, and traceroute
    """
    cmd = NmapCommand()
    command = [cmd.command_name] + cmd.port_args(ports) + ["-T4", "-A", target]
    return cmd.execute(command)

def noping_version_scan_action(target: str, ports: Optional[list[str]] = None) -> str:
    """
    Recommended scan: -Pn -sV
    """
    cmd = NmapCommand()
    command = [cmd.command_name] + cmd.port_args(ports) + ["-Pn", "-sV", target]
    return cmd.execute(command)

def script_scan_action(target: str, script: str, ports: list[str]) -> str:    #ports are required for a script scan
    """
    Vulnerability/script scan (-sV --script <script>)
    """
    cmd = NmapCommand()
    command = [cmd.command_name] + cmd.port_args(ports) + ["-sV", f"--script={script.strip()}", target]
    return cmd.execute(command)

# if __name__ == "__main__":
#     # Test example
#     print(basic_scan_action("10.1.1.106"))
#     print(recommended_scan_action("127.0.0.1",[80,22,145]))
