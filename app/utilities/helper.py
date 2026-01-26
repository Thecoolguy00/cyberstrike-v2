import asyncio
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from app.utilities import dc_logger
from app.utilities.singletons_factory import DcSingleton
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import ToolException as LangChainToolException
from app.utilities.constants import Constants
from mcp.shared.exceptions import McpError

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__), {"Chat2Test": "V1"})


class Helper(metaclass = DcSingleton):
    
    @staticmethod
    async def timeout_tool_wrapper(request, handler, timeout: float = None):
        """
        Async timeout wrapper for ToolNode.awrap_tool_call.
        Runs the async handler directly with asyncio.wait_for.
        
        Args:
            request: Tool request object
            handler: Async handler function
            timeout: Timeout in seconds (uses TOOL_TIMEOUT from config if None)
        
        Returns:
            Tool execution result
        
        Raises:
            LangChainToolException: If timeout or execution error occurs
        """
        if timeout is None:
            automation_config = Constants.fetch_constant("playwright_tool_timeout")
            timeout = automation_config if automation_config is not None else 30.0
        try:
            # handler is async, so we can await it safely
            return await asyncio.wait_for(handler(request), timeout=timeout)

        except asyncio.TimeoutError:
            logger.error(f"Tool execution timed out after {timeout} seconds for tool call ID: {request.tool_call['id']}")
            # Raise ToolException for timeout errors (tool execution errors)
            raise LangChainToolException(
                f"Tool execution timeout: exceeded {timeout} seconds for tool '{request.tool_call.get('name', 'unknown')}'"
            )

        except McpError as e:
            logger.error(f"MCP error in tool execution: {e}")
            # Raise ToolException for MCP errors (tool execution errors)
            raise LangChainToolException(f"MCP Error: {str(e)}")

        except Exception as e:
            logger.error(f"Unexpected error in tool execution: {e}", exc_info=True)
            # Raise ToolException for general errors (tool execution errors)
            raise LangChainToolException(f"Tool execution error: {str(e)}")
    
    @staticmethod
    @retry(retry=retry_if_exception_type((OutputParserException, Exception)), stop=stop_after_attempt(3), wait=wait_fixed(2))
    def send_llm_request(llm:BaseChatModel, messages, output_parser: PydanticOutputParser = None, tools: list = None, pro = False):
        try:
            parsed_response = None
            if tools:
                if pro:
                    response = llm.bind_tools(tools).invoke(messages)
                else:
                    response = llm.bind_tools(tools).invoke(messages)
            else:
                if pro:
                    response = llm.invoke(messages)
                else:
                    response = llm.invoke(messages)
            if hasattr(response, "tool_calls") and len(response.tool_calls) == 0:
                if not response.content:
                    raise ValueError("No content returned from LLM")

                if output_parser:
                    if isinstance(response.content, list):
                        if isinstance(response.content[0], dict) and "text" in response.content[0]:
                            parsed_response=output_parser.parse(response.content[0]["text"])
                        else:
                            parsed_response = output_parser.parse("\n".join(response.content))
                            response.content = "\n".join(response.content)
                    else:
                        parsed_response = output_parser.parse(response.content)
            return response, parsed_response
        except Exception as e:
            logger.error(f"Error in sending llm request: {e}")
            raise e
        except OutputParserException as exe:
            logger.error(f"OutputParserException in sending llm request: {exe}", exc_info= True)
            raise exe