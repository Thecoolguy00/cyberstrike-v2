from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, model_validator
from langchain_core.messages import AIMessage, AnyMessage
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type, before_sleep
from langchain_core.output_parsers import PydanticOutputParser
import json
from app.utilities import dc_logger
logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))

#extracting text from different message schema, here because importing parser as a standalone in ipynb raises a error
def extract_text(msg) -> str:
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
    thinking: str=Field(..., description="Reasoning or explanation")
    message: Optional[str]=Field(None, description="Natural language reply for the user")
    tool_name: Optional[str]=Field(None, description="Name of the tool to call")
    args: Optional[Dict[str, Any]]=Field(None, description="Arguments for the tool call")

    @model_validator(mode="before")
    def normalize_empty_strings(cls, values):
        for key in ("message", "tool_name", "args"):
            if values.get(key) == "":
                values[key] = None
        return values

    @model_validator(mode="after")
    def validate_schema(self):
        has_message = self.message is not None
        has_tool = self.tool_name is not None
        has_args = self.args is not None and len(self.args) > 0

        if has_message:
            if has_tool or has_args:
                raise ValueError(
                    "If 'message' is present, 'tool_name' and 'args' must not be present"
                )
            return self

        if has_tool:
            if not has_args:
                raise ValueError(
                    "If 'tool_name' is present, 'args' must be a non-empty object"
                )
            return self

        raise ValueError(
            "Response must contain either 'thinking' and 'message' OR 'thinking' and ('tool_name' and 'args')"
        )

    

#parser
parser=PydanticOutputParser(pydantic_object=AgentResponse)

def log_retry(retry_state):
    err = retry_state.outcome.exception()
    logger.error(f"[RETRY] {retry_state.attempt_number} due to {type(err).__name__}")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type((ValueError, json.JSONDecodeError)), 
    reraise=True,
    before_sleep=log_retry
)
def invoke_and_validate(llm, messages):

    response=llm.invoke(messages)
    raw_data=extract_text(response.content)
    
    #validate and retry on error
    parsed=parser.parse(raw_data)

    #replaced the response.content with flatened dict of validated pydantic object
    response.content=parsed.model_dump_json()
    return response

