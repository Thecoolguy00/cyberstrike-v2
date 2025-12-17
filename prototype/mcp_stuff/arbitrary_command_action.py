#-------------------------------------------
#           BE CAREFUL WITH THIS
#-------------------------------------------

#NOTE: In langgraph, make this as a seperate node and add interrupt before
#       This script is currently blacklisted in validator.py

from prototype.mcp_stuff.kali_command import CommandRunner
from prototype.mcp_stuff.validators import contains_shell_metacharacters

def custom_command(cmd,timeout: int=120)->str:
    """
    Execute any arbitrary system command and return its combined output.
    
    Args:
        cmd (str | list): Command string or list of arguments.
        timeout (int): Optional timeout in seconds (default 200).
    
    Returns:
        str: Combined stdout + stderr output or error message.
    """
    if contains_shell_metacharacters([cmd] if isinstance(cmd,str) else cmd):
        return "commnd not allowed"
    
    runner=CommandRunner(command_name="custom",timeout=timeout)
    return runner.execute(cmd)

if __name__ == "__main__":
    print(contains_shell_metacharacters(["curl", "http://example.com;rm", "-I"])) #True, bad command
    print(custom_command(["cmd","/c","dir","&","dir"])) #command not allowed, bad command
    
#NOTE: In langgraph, make this as a seperate node and add interrupt before