from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, model_validator
from langchain_core.messages import AIMessage, AnyMessage
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type, before_sleep
from langchain_core.output_parsers import PydanticOutputParser
import json
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))

def extract_text(msg) -> str:
    """Extract text from different message schemas."""
    if isinstance(msg, str):
        return msg

    if isinstance(msg, list):
        out = []
        for part in msg:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict) and "text" in part:
                out.append(part["text"])
        return "\n".join(out)

    return str(msg)


class AgentResponse(BaseModel):
    """Unified agent response schema."""
    tool: Optional[str] = Field(None, description="Tool name or null")
    args: Optional[Dict[str, Any]] = Field(None, description="Tool arguments or null")
    message: Optional[str] = Field(None, description="Response text or null")

    @model_validator(mode="before")
    def normalize_empty_values(cls, values):
        """Convert empty strings and empty dicts to None."""
        for key in ("tool", "message"):
            if values.get(key) == "":
                values[key] = None
        
        # Handle empty args dict
        if values.get("args") is not None and len(values.get("args", {})) == 0:
            values["args"] = None
            
        return values

    @model_validator(mode="after")
    def validate_mutual_exclusion(self):
        """Ensure tool OR message, never both."""
        has_message = self.message is not None
        has_tool = self.tool is not None
        has_args = self.args is not None

        # Case 1: Message response
        if has_message:
            if has_tool or has_args:
                raise ValueError(
                    "Cannot have both 'message' and tool fields. "
                    "Set tool=null and args=null when using message."
                )
            return self

        # Case 2: Tool call
        if has_tool:
            if not has_args:
                raise ValueError(
                    f"Tool '{self.tool}' requires 'args' as a non-empty dict"
                )
            if has_message:
                raise ValueError(
                    "Cannot have both 'tool' and 'message'. "
                    "Set message=null when using a tool."
                )
            return self

        # Case 3: Invalid - neither message nor tool
        raise ValueError(
            "Response must have either 'message' (with tool=null, args=null) "
            "OR 'tool' + 'args' (with message=null)"
        )


# Parser instance
parser = PydanticOutputParser(pydantic_object=AgentResponse)


def log_retry(retry_state):
    """Log retry attempts."""
    err = retry_state.outcome.exception()
    logger.warning(
        f"Retry attempt {retry_state.attempt_number}/3 - "
        f"Error: {type(err).__name__}: {str(err)}"
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type((ValueError, json.JSONDecodeError)),
    reraise=True,
    before_sleep=log_retry
)
def invoke_and_validate(llm, messages):
    """Invoke LLM and validate response against schema with retries."""
    
    # Get raw response
    response = llm.invoke(messages)
    raw_data = extract_text(response.content)
    
    # Log raw response for debugging
    logger.debug(f"Raw LLM response: {raw_data[:200]}...")
    
    # Parse and validate
    try:
        from prototype.sub_agents.helper import extract_json_block
        clean_data = extract_json_block(raw_data)
        parsed = parser.parse(clean_data)
    except Exception as e:
        logger.error(f"Parse error: {e}\nRaw: {raw_data}")
        raise
    
    # Extract native thinking
    from prototype.sub_agents.helper import extract_native_thinking
    native_thinking = extract_native_thinking(response)

    # Fallback to checking if model still generated thinking inside JSON block
    if not native_thinking:
        try:
            json_data = json.loads(clean_data)
            native_thinking = json_data.get("thinking", "")
        except Exception:
            pass

    # Replace content with validated JSON including native thinking
    response_dict = parsed.model_dump()
    response_dict["thinking"] = native_thinking
    response.content = json.dumps(response_dict)
    
    # Log parsed fields for debugging
    logger.info(
        f"Validated response - "
        f"Tool: {parsed.tool or 'none'}, "
        f"Message: {'yes' if parsed.message else 'no'}"
    )
    
    return response


def extract_agent_decision(response: AIMessage) -> tuple[Optional[str], Optional[dict], Optional[str]]:
    """
    Extract tool, args, and message from validated response.
    
    Returns:
        (tool_name, args, message) tuple
    """
    try:
        data = json.loads(response.content)
        return data.get("tool"), data.get("args"), data.get("message")
    except json.JSONDecodeError:
        logger.error(f"Failed to decode response content: {response.content}")
        return None, None, None