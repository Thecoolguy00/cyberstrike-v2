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

def intense_scan_action(target: str, ports: Optional[list[int]] = None) -> str:
    """
    Intense scan (-T4 -A)
    Includes: OS detection, version detection, script scanning, and traceroute
    """
    cmd = NmapCommand()
    command = [cmd.command_name] + cmd.port_args(ports) + ["-T4", "-A", target]
    return cmd.execute(command)

def no_ping_scan_action(target: str, ports: Optional[list[int]] = None) -> str:
    """
    No-ping scan (-Pn)
    """
    cmd = NmapCommand()
    command = [cmd.command_name] + cmd.port_args(ports) + ["-Pn", target]
    return cmd.execute(command)

def recommended_scan_action(target: str, ports: Optional[list[int]] = None) -> str:
    """
    Recommended scan: -Pn -sV
    """
    cmd = NmapCommand()
    command = [cmd.command_name] + cmd.port_args(ports) + ["-Pn", "-sV", target]
    return cmd.execute(command)

def script_scan_action(target: str, script: str, ports: list[int]) -> str:    #ports are required for a script scan
    """
    Vulnerability/script scan (-sV --script <script>)
    """
    cmd = NmapCommand()
    command = [cmd.command_name] + cmd.port_args(ports) + ["-sV", "--script", script, target]
    return cmd.execute(command)

# if __name__ == "__main__":
#     # Test example
#     print(basic_scan_action("10.1.1.106"))
#     print(recommended_scan_action("127.0.0.1",[80,22,145]))
