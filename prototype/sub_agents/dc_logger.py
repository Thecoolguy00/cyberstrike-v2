import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# ANSI escape codes for colors
class Colors:
    RESET = "\033[0m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BOLD = "\033[1m"

class ColoredFormatter(logging.Formatter):
    """
    Custom formatter to add colors to log levels.
    """
    COLORS = {
        logging.DEBUG: Colors.CYAN,
        logging.INFO: Colors.GREEN,
        logging.WARNING: Colors.YELLOW,
        logging.ERROR: Colors.RED,
        logging.CRITICAL: Colors.RED + Colors.BOLD,
    }

    def format(self, record):
        log_color = self.COLORS.get(record.levelno, Colors.WHITE)
        
        # Format the timestamp
        asctime = self.formatTime(record, self.datefmt)
        
        # Format the level name with color
        levelname = f"{log_color}{record.levelname:<8}{Colors.RESET}"
        
        # Format the location (filename:lineno)
        location = f"{Colors.MAGENTA}{record.filename}:{record.lineno}{Colors.RESET}"
        
        # Format the function name
        func_name = f"{Colors.BLUE}{record.funcName}{Colors.RESET}"
        
        # Format the message
        message = record.getMessage()

        # Construct the final log message
        # Format: TIMESTAMP : LEVEL : LOCATION : FUNCTION --> MESSAGE
        return f"{asctime} : {levelname} : {location} : {func_name} --> {message}"

def get_logger(name, level=logging.INFO, file_name="logs/app.logs"):
    """
    Returns a logger configured with colored console output and rotating file output.
    """
    logger = logging.getLogger(name)
    
    # Prevent adding handlers multiple times if get_logger is called repeatedly
    if logger.hasHandlers():
        return logger

    logger.setLevel(level)

    # --- Console Handler (Colored) ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = ColoredFormatter(
        fmt="%(asctime)s : %(levelname)s : %(filename)s:%(lineno)d : %(funcName)s --> %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # --- File Handler (Rotating, Non-Colored) ---
    try:
        if not os.path.exists(os.path.dirname(file_name)):
            os.makedirs(os.path.dirname(file_name), exist_ok=True)
            
        # Rotate logs: Max 10MB per file, keep 5 backups
        file_handler = RotatingFileHandler(
            file_name, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_formatter = logging.Formatter(
            fmt="%(asctime)s : %(levelname)-8s : %(filename)s:%(lineno)d : %(funcName)-20s --> %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        # Fallback if file logging fails (e.g. permission issues)
        print(f"{Colors.RED}Failed to setup file logging: {e}{Colors.RESET}")

    return logger

class LoggerAdap(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return '%s' % (msg), kwargs