from typing import List, Optional, Union
from pydantic import BaseModel, Field, ValidationError, model_validator

class Initiative(BaseModel):
    Title: str = Field(..., min_length=3)
    Date: Optional[str] = None
    Initiative_Summary: Optional[str] = Field(None, alias="Initiative Summary")
    Source_URL: Optional[str] = Field(None, alias="Source URL")

    model_config = {
        "populate_by_name": True,
        "extra": "forbid"
    }

class NoInitiatives(BaseModel):
    Title: str

    @model_validator(mode="after")
    def check_exact_message(self):
        if self.Title != "No verifiable recent initiatives found.":
            raise ValueError("Invalid sentinel message")
        return self

    model_config = {
        "extra": "forbid"
    }

StructuredOutput = List[Union[Initiative, NoInitiatives]]

import json

def parse_structured_output(text) -> StructuredOutput:
    """
    Manual Pydantic parser for structured LLM output.
    Use ONLY when the response is not a tool call.
    """

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model output is not valid JSON:\n{text}") from e

    if not isinstance(data, list):
        raise ValueError("Structured output must be a list")

    try:
        validated = [ 
            Initiative.model_validate(item) if "Source URL" in item
            else NoInitiatives.model_validate(item)
            for item in data
        ]
    except ValidationError as e:
        raise ValueError(f"Structured output validation failed:\n{e}") from e

    return validated


from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
import json
from pydantic import ValidationError

@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(5),
    retry=retry_if_exception_type((ValueError, json.JSONDecodeError, ValidationError)),
    reraise=True
)
def invoke_and_validate(llm, messages):
    response = llm.invoke(messages)

    # Tool call → do NOT validate
    if hasattr(response, "tool_calls") and response.tool_calls:
        return response

    # Validate strict structured output
    parse_structured_output(response.content)

    return response
