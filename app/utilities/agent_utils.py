"""
Common Agent Utilities
Shared utilities for all LangGraph agents to reduce code duplication and improve consistency.
"""
from typing import Dict, Any, Optional, List
from functools import wraps
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(
    dc_logger.get_logger(__name__), {"service": "AgentUtils"}
)


def safe_agent_node(node_name: str, return_on_error: Optional[Dict] = None):
    """
    Decorator for agent nodes to handle errors consistently with logging.
    
    Args:
        node_name: Name of the node for logging
        return_on_error: Default return value on error (if None, returns error dict)
    
    Usage:
        @safe_agent_node("research_node")
        async def research_node(state: AgentState):
            # node logic
            return result
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(state, *args, **kwargs):
            logger.info(f"[{node_name}] Starting execution")
            try:
                result = await func(state, *args, **kwargs)
                logger.info(f"[{node_name}] Completed successfully")
                return result
            except Exception as e:
                error_msg = f"[{node_name}] Error: {str(e)}"
                logger.error(error_msg, exc_info=True)
                
                if return_on_error is not None:
                    return {**return_on_error, "errors": [error_msg]}
                return {"errors": [error_msg]}
        
        # Handle sync functions
        if not hasattr(func, '__await__'):
            @wraps(func)
            def sync_wrapper(state, *args, **kwargs):
                logger.info(f"[{node_name}] Starting execution")
                try:
                    result = func(state, *args, **kwargs)
                    logger.info(f"[{node_name}] Completed successfully")
                    return result
                except Exception as e:
                    error_msg = f"[{node_name}] Error: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    
                    if return_on_error is not None:
                        return {**return_on_error, "errors": [error_msg]}
                    return {"errors": [error_msg]}
            return sync_wrapper
        
        return wrapper
    return decorator


def log_node_transition(from_node: str, to_node: str, state: Optional[Dict] = None):
    """Log transitions between nodes with optional state info."""
    logger.debug(f"Transition: {from_node} -> {to_node}")
    if state:
        logger.debug(f"State keys: {list(state.keys())}")


def safe_get_state_value(state: Dict, key: str, default: Any = None, required: bool = False) -> Any:
    """
    Safely extract values from state with optional validation.
    
    Args:
        state: The state dictionary
        key: Key to extract
        default: Default value if key not found
        required: If True, logs warning when key missing
    
    Returns:
        The value from state or default
    """
    value = state.get(key, default)
    
    if required and value is None:
        logger.warning(f"Required state key '{key}' is missing or None")
    
    return value


def merge_errors(existing_errors: Optional[List[str]], new_error: str) -> List[str]:
    """
    Merge new error with existing errors list.
    
    Args:
        existing_errors: Existing errors list or None
        new_error: New error message to add
    
    Returns:
        Updated errors list
    """
    if existing_errors is None:
        return [new_error]
    return existing_errors + [new_error]


def format_llm_context(data: Dict[str, Any], max_length: int = 100000) -> str:
    """
    Format data dictionary as context string for LLM with truncation.
    
    Args:
        data: Data dictionary to format
        max_length: Maximum character length
    
    Returns:
        Formatted string
    """
    formatted = "\n\n".join(f"**{k}**:\n{v}" for k, v in data.items() if v)
    if len(formatted) > max_length:
        logger.warning(f"Context truncated from {len(formatted)} to {max_length} chars")
        return formatted[:max_length] + "\n\n[CONTENT TRUNCATED]"
    return formatted


def create_empty_response(key: str) -> Dict[str, Dict]:
    """
    Create empty response dictionary for a specific output key.
    
    Args:
        key: The output key name
    
    Returns:
        Dict with empty dict for the key
    """
    return {key: {}}


def validate_urls(urls: Optional[List[str]], fallback: Optional[List[str]] = None) -> List[str]:
    """
    Validate and filter URLs, with optional fallback.
    
    Args:
        urls: List of URLs to validate
        fallback: Fallback URLs if primary list is empty
    
    Returns:
        Validated list of URLs
    """
    if not urls or not isinstance(urls, list):
        return fallback or []
    
    # Filter out None, empty strings, and invalid URLs
    valid_urls = [url for url in urls if url and isinstance(url, str) and url.strip()]
    
    if not valid_urls and fallback:
        logger.info(f"No valid URLs found, using fallback: {len(fallback)} URLs")
        return fallback
    
    return valid_urls
