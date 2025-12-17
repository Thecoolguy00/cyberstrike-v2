from kali_command import CommandRunner

class CurlCommand(CommandRunner):
    def __init__(self):
        super().__init__("curl",timeout=30)

def get_headers_action(url:str)->str:
    """Return HTTP headers (curl -I)"""
    cmd=CurlCommand()
    
    return cmd.execute([cmd.command_name,"-I",url])

def get_page_content(url:str)->str:
    """Return full page content (curl -sL)"""
    cmd=CurlCommand()
    #clean the page content of scripts and style sheets later
    return cmd.execute([cmd.command_name,"-sL",url])

if __name__ == "__main__":
    print(get_headers_action("https://www.wikipedia.org/"))
    print("\n\n\n")
    print(get_page_content("https://www.wikipedia.org/"))

        
        #add headers mimicking a real browser for passing through simple bot detection