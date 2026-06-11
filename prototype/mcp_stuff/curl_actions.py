from prototype.mcp_stuff.kali_command import CommandRunner
from prototype.mcp_stuff.helper import encode_url_params

class CurlCommand(CommandRunner):
    def __init__(self):
        super().__init__("curl",timeout=30)

def get_headers_action(url: str) -> str:
    """Return HTTP headers (curl -I)"""
    cmd = CurlCommand()
    return cmd.execute([cmd.command_name, "-I", encode_url_params(url)])

def get_full_page_action(url: str) -> str:
    """Return full page content (curl -sL)"""
    cmd = CurlCommand()
    return cmd.execute([cmd.command_name, "-sL", encode_url_params(url)])

def get_partial_page_action(url: str, size_limit: int = 2000) -> str:
    """Return partial page according to the size limit"""
    cmd = CurlCommand()
    output = cmd.execute([cmd.command_name, "-sL", encode_url_params(url)])
    return output[:size_limit]

if __name__ == "__main__":
    print(get_headers_action("https://www.wikipedia.org/"))
        
        #add headers mimicking a real browser for passing through simple bot detection