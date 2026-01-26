from app.services.llm_services.llm_implementation.gemini_models import Gemini25FlashLLM, Gemini25FlashLiteLLM, Gemini25ProLLM
from app.services.llm_services.llm_implementation.openai_models import GPT4oLLM, GPT4oMiniLLM, O1PreviewLLM, O1MiniLLM
from app.services.llm_services.llm_implementation.groq_models import Llama3GroqLLM, MoonshotKimiGroqLLM, GPTOSS120bGroqLLM
from app.services.llm_services.llm_interface import LLMInterface
from app.utilities.dc_enums import SupportedLlms


class LlmFactory:
        
    @staticmethod
    def get_llm(type: str) -> LLMInterface:
        """
        Factory method to get an LLM instance based on the given type.

        Args:
            type (str): The type of LLM to instantiate.

        Returns:
            LLMInterface: An instance of the LLM class corresponding to the given type.

        Raises:
            ValueError: If no matching LLM implementation is found for the given type.
        """
        if type == SupportedLlms.LLAMA3_GROQ_70B_VERSATILE.value:
            return Llama3GroqLLM()
        elif type == SupportedLlms.MOONSHOT_KIMI_K2_INSTRUCT_0905.value:
            return MoonshotKimiGroqLLM()
        elif type == SupportedLlms.GPT_OSS_120B.value:
            return GPTOSS120bGroqLLM()
        elif type == SupportedLlms.GEMINI_2_5_FLASH.value:
            # import and return the GEMINI_2_5_FASH implementation
            return Gemini25FlashLLM()
        elif type == SupportedLlms.GEMINI_2_5_FLASH_LITE.value:
            # return the GEMINI_2_0_FLASH_LITE implementation
            return Gemini25FlashLiteLLM()
        elif type == SupportedLlms.GEMINI_2_5_PRO.value:
            return Gemini25ProLLM()
        elif type == SupportedLlms.GPT_4O.value:
            return GPT4oLLM()
        elif type == SupportedLlms.GPT_4O_MINI.value:
            return GPT4oMiniLLM()
        elif type == SupportedLlms.O1_PREVIEW.value:
            return O1PreviewLLM()
        elif type == SupportedLlms.O1_MINI.value:
            return O1MiniLLM()
        else:
            raise ValueError(f"No matching LLM implementation found for type: {type}")