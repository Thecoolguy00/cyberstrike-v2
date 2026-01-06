import re
import ipaddress
from typing import List

# -----------------------------
# Regex patterns (simple & readable)
# -----------------------------

# Accept only http/https URLs (must include scheme)
_RE_URL = re.compile(r"^https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+$")

# Host: either hostname-like (letters, digits, hyphen, dot) OR dotted-quad (validated later)
_RE_HOST = re.compile(r"^[A-Za-z0-9\-\.]+$")

# Ports: numbers, commas and hyphens (e.g. 22,80,8000-8100)
_RE_PORTS = re.compile(r"^[0-9,\-]+$")

# Characters that commonly indicate shell chaining / command injection
_SHELL_META_CHARS = set(";|&`$><(){}[]")

# Regex to catch other nasty tricks like '&&' or subshells
_META_REGEX = re.compile(r"[;&|`$><(){}\[\]]") 

# -----------------------------
# Helper functions
# -----------------------------

def contains_shell_metacharacters(args:List[str])->bool:
    """
    Quickly rejects: if any shell metacharacters apppears in the joined arsg,
    it's almost certainly an attempt at chaining/injection
    """
    if not args:
        return False
    joined=" ".join(map(str,args))
    if any(ch in joined for ch in _SHELL_META_CHARS):
        return True
    
     #regex that handles double symbols like &&,|| and other metas
    if _META_REGEX.search(joined):
        return True
    
    return False

def is_valid_url(s:str)->bool:
    """Validates HTTP/HTTPS URL structure"""
    if not isinstance(s,str):
        return False
    return bool(_RE_URL.match(s))

def is_valid_host_or_ip(s:str)->bool:
    """
    validate host or ipv4 addr.
    -if looks like numeric dotted-quad, chech with ipaddress for 0-255 ranges
    -otherwise, ensure it matches the simple hostname pattern (no slashes)
    """
    if not isinstance(s,str) or not s:
        return False
    
    if "/" in s or " " in s:
        return False
    
    #ipv4 check
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}",s):
        try:
            ipaddress.IPv4Address(s)
            return True
        except ipaddress.AddressValueError:
            return False
    
    #otherwise, hostname check
    return bool(_RE_HOST.match(s))

def is_valid_ports(s:str)->bool:
    """basic check for port lists/range like 22,80,8000-8100"""
    if not isinstance(s,str) or not s:
        return False
    if not _RE_PORTS.match(s):
        return False
    
    return True


# -----------------------------
# Validators (simple flow)
# -----------------------------
def validate_curl(args: List[str])->bool:
    """
    Allowed examples:
      curl -I http://example.com
      curl http://example.com
    Rules:
      - First token must be 'curl'
      - Last token must be a URL
      - Must not contain shell metacharacters
      - Must contain at least one valid http(s) URL among args
    """
    if not args or str(args[0]).lower() != "curl":
        return False
    if contains_shell_metacharacters(args):
        return False
    
    return is_valid_url(args[-1])

def validate_nmap(args: List[str])->bool:
    """
    Allowed examples:
      nmap -p 22,80 192.168.0.1
      nmap example.com
    Rules:
      - First token 'nmap'
      - No shell metacharacters
      - If '-p' or '--ports' present, next token must be valid ports
      - Last non-option token should be a host or IP
    """
    if not args or str(args[0]).lower() != "nmap":
        return False
    if contains_shell_metacharacters(args):
        return False
    
    #check for port values when -p/--ports 
    for i,a in enumerate(args):
        if a in ("-p","--ports") and i+1<len(args):
            if not is_valid_ports(str(args[i+1])):
                return False
    
    #last token should be host
    return is_valid_host_or_ip(args[-1])

def validate_feroxbuster(args:list[str])->bool:
    """
    Allowed examples:
      feroxbuster -u http://target.com -w /path/wordlist.txt
      feroxbuster --url https://target.com
    Rules:
      - First token 'feroxbuster'
      - No shell metacharacters
      - Must include -u or --url followed by a valid http(s) URL
    """
    if not args or str(args[0]).lower() != "feroxbuster":
        return False
    if contains_shell_metacharacters(args):
        return False
    
    for i,a in enumerate(args):
        if a in ("-u","--url") and i+1<len(args):
            if is_valid_url(str(args[i+1])):
                return True
    
    return False

def validate_dalfox(args:list[str])->bool:

    if not args or str(args[0]).lower() != "dalfox":
        return False
    if contains_shell_metacharacters(args):
        return False
    
    for i,a in enumerate(args):
        if a=="url" and i+1<len(args):
            if is_valid_url(str(args[i+1])):
                return True
    return False

def validate_xsstrike(args:list[str])->bool:

    if not args or str(args[0]).lower() != "xsstrike":
        return False
    if contains_shell_metacharacters(args):
        return False
    
    for i,a in enumerate(args):
        if a in ("-u","--url") and i+1<len(args):
            if is_valid_url(str(args[i+1])):
                return True
            
    return False

# -----------------------------
# Dispatcher
# -----------------------------
VALIDATORS={
    "curl":validate_curl,
    "nmap":validate_nmap,
    "feroxbuster":validate_feroxbuster,
    "dalfox":validate_dalfox,
    "xsstrike":validate_xsstrike
}

def validate_command(args:list[str])->bool:
    """
    Generic entrypoint:
      - If the command name (args[0]) has a validator, run it.
      - Otherwise return False (unknown commands are rejected).
    """
    if not args:
        return False
    cmd=str(args[0])
    fn=VALIDATORS.get(cmd)
    if not fn:
        return False
    
    return fn(args)