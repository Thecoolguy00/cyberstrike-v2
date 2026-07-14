from app.services.llm_services.llm_implementation.groq_models import GPTOSS120bGroqLLM
from app.services.llm_services.llm_implementation.openrouter_models import (
    DeepseekV4FlashOpenRouterLLM,
    DeepseekV4ProOpenRouterLLM,
    TencentHy3PreviewOpenRouterLLM,
)
from app.services.llm_services.llm_interface import LLMInterface
from app.utilities.dc_enums import SupportedLlms


class LlmFactory:
        
    @staticmethod
    def get_llm(
        type: str,
        reasoning_effort: str | None = None,
    ) -> LLMInterface:
        """
        Factory method to get an LLM instance based on the given type.

        Args:
            type (str): The type of LLM to instantiate.
            reasoning_effort (str | None): Optional OpenRouter reasoning effort level.

        Returns:
            LLMInterface: An instance of the LLM class corresponding to the given type.

        Raises:
            ValueError: If no matching LLM implementation is found for the given type.
        """
        if type == SupportedLlms.GPT_OSS_120B.value:
            return GPTOSS120bGroqLLM()
        elif type == SupportedLlms.DEEPSEEK_V4_FLASH_OPENROUTER.value:
            return DeepseekV4FlashOpenRouterLLM(
                reasoning_effort=reasoning_effort,
            )
        elif type == SupportedLlms.DEEPSEEK_V4_PRO_OPENROUTER.value:
            return DeepseekV4ProOpenRouterLLM(
                reasoning_effort=reasoning_effort,
            )
        elif type == SupportedLlms.TENCENT_HY3_PREVIEW_OPENROUTER.value:
            return TencentHy3PreviewOpenRouterLLM(
                reasoning_effort=reasoning_effort,
            )
        else:
            raise ValueError(f"No matching LLM implementation found for type: {type}")