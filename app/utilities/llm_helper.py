"""
LLM Helper Utility
Provides a centralized way to retrieve LLM instances based on configuration.
"""
from typing import Optional, List, Dict, Any
from functools import lru_cache
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.services.llm_services.llm_implementation.llm_factory import LlmFactory
from app.utilities.constants import Constants
from app.services.llm_services.llm_interface import LLMInterface
from app.utilities import dc_logger

logger = dc_logger.LoggerAdap(
    dc_logger.get_logger(__name__), {"service": "LLMHelper"}
)


class LLMHelper:
    """
    Helper class to get LLM instances based on constants configuration.
    Provides a single entry point for all LLM operations across the application.
    Includes caching and optimized invocation methods.
    """
    
    # Cache LLM configuration to avoid repeated YAML reads
    _config_cache: Optional[Dict] = None
    
    @classmethod
    @lru_cache(maxsize=10)
    def _get_llm_config(cls) -> Dict:
        """Cache LLM configuration to avoid repeated YAML reads."""
        if cls._config_cache is None:
            cls._config_cache = Constants.fetch_constant("llm_models")
        return cls._config_cache
    
    @staticmethod
    @lru_cache(maxsize=10)
    def get_llm_for_service(
        service_name: str = None,
        reasoning_effort: str | None = None,
    ) -> BaseChatModel:
        """
        Get an LLM instance for a specific service or use the default.
        Results are cached for better performance.
        
        Args:
            service_name (str, optional): The service name to get a specific model for.
                                         If None, returns the default model.
        
        Returns:
            BaseChatModel: A LangChain chat model instance ready to use.
        """
        llm_config = LLMHelper._get_llm_config()
        
        # Try to get service-specific model, fallback to default
        if service_name and service_name in llm_config:
            model_name = llm_config[service_name]
        else:
            model_name = llm_config.get("default_model", "deepseek_v4_flash_openrouter")
        
        # Get the LLM wrapper from factory and return the actual LLM
        llm_wrapper: LLMInterface = LlmFactory.get_llm(
            model_name,
            reasoning_effort=reasoning_effort,
        )
        return llm_wrapper.get_llm()
    
    @staticmethod
    @lru_cache(maxsize=10)
    def get_llm_wrapper_for_service(
        service_name: str = None,
        reasoning_effort: str | None = None,
    ) -> LLMInterface:
        """
        Get an LLM wrapper (interface) for a specific service.
        Results are cached for better performance.
        
        Args:
            service_name (str, optional): The service name to get a specific model for.
        
        Returns:
            LLMInterface: The LLM wrapper instance.
        """
        llm_config = LLMHelper._get_llm_config()
        
        # Try to get service-specific model, fallback to default
        if service_name and service_name in llm_config:
            model_name = llm_config[service_name]
        else:
            model_name = llm_config.get("default_model", "deepseek_v4_flash_openrouter")
        
        return LlmFactory.get_llm(
            model_name,
            reasoning_effort=reasoning_effort,
        )
    
    @staticmethod
    def get_default_model_name() -> str:
        """
        Get the default model name from configuration.
        
        Returns:
            str: The default model name.
        """
        llm_config = LLMHelper._get_llm_config()
        return llm_config.get("default_model", "deepseek_v4_flash_openrouter")
    
    @staticmethod
    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def invoke_with_structured_output(
        service_name: str,
        schema: type[BaseModel],
        messages: List[BaseMessage],
        log_prefix: str = ""
    ) -> BaseModel:
        """
        Invoke LLM with structured output and automatic retry logic.
        
        Args:
            service_name: Service name for LLM selection
            schema: Pydantic model class for structured output
            messages: List of messages to send to LLM
            log_prefix: Optional prefix for log messages
        
        Returns:
            Pydantic model instance with structured output
        
        Raises:
            Exception: If all retry attempts fail
        """
        try:
            llm = LLMHelper.get_llm_for_service(service_name)
            structured_llm = llm.with_structured_output(schema)
            result = await structured_llm.ainvoke(messages)
            
            if log_prefix:
                logger.info(f"{log_prefix}: Successfully generated structured output")
            
            return result
            
        except Exception as e:
            error_msg = f"{log_prefix}: LLM invocation failed - {str(e)}" if log_prefix else f"LLM invocation failed - {str(e)}"
            logger.error(error_msg)
            raise
    
    @staticmethod
    def build_messages(
        system_prompt: str,
        user_content: str,
        format_vars: Optional[Dict[str, Any]] = None
    ) -> List[BaseMessage]:
        """
        Build messages list with optional formatting.
        
        Args:
            system_prompt: System message content
            user_content: User message content
            format_vars: Optional dict for formatting system prompt
        
        Returns:
            List of BaseMessage instances
        """
        if format_vars:
            system_prompt = system_prompt.format(**format_vars)
        
        return [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content)
        ]
