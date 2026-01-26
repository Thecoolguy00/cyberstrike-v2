from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

from langchain_core.language_models.chat_models import BaseChatModel
from app.services.llm_services.llm_interface import LLMInterface
from app.utilities.singletons_factory import DcSingleton

load_dotenv()

class Gemini25FlashLLM(LLMInterface,metaclass=DcSingleton):
    def __init__(self, temperature: float = 1.0, rate_limiter=None):
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-flash-latest",
            temperature=temperature, 
            # include_thoughts = False,
            thinking_budget=1024,
            rate_limiter=rate_limiter
            )

    def get_llm(self) -> BaseChatModel:
        """
        Static method to get an instance of Gemini25FlashLLM.

        Returns:
            Gemini25FlashLLM: An instance of the Gemini25FlashLLM class.
        """
        return self.llm

    def generate(self, prompt: str) -> str:
        """
        Generates output from Gemini 2.5 Flash model for the given prompt.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The generated output from the LLM.
        """
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        """
        Asynchronously generates output from Gemini 2.5 Flash model for the given prompt.
        Uses the tasynchronous `ainvoke` method of the underlying LLM.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The asynchronously generated output from the LLM.
        """
        return (await self.llm.ainvoke(prompt)).content


class Gemini25FlashLiteLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(self, temperature: float = 1.0):
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash-lite",
            temperature=temperature,
            api_key=None,
            include_thoughts = False
        )

    def get_llm(self) -> BaseChatModel :
        """
        Static method to get an instance of Gemini25FlashLLM.

        Returns:
            Gemini25FlashLLM: An instance of the Gemini25FlashLLM class.
        """
        return self.llm

    def generate(self, prompt: str) -> str:
        """
        Generates output from Gemini 2.5 Flash model for the given prompt.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The generated output from the LLM.
        """
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        """
        Asynchronously generates output from Gemini 2.5 Flash Lite model for the given prompt.
        Uses the asynchronous `ainvoke` method of the underlying LLM.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The asynchronously generated output from the LLM.
        """
        return (await self.llm.ainvoke(prompt)).content
    
class Gemini25ProLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(self, temperature: float = 1.0):
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-pro",
            temperature=temperature,
            api_key=None,
            thinking_budget=0,
            include_thoughts = False
        )

    def get_llm(self)->BaseChatModel:
        """
        Static method to get an instance of Gemini25FlashLLM.

        Returns:
            Gemini25FlashLLM: An instance of the Gemini25FlashLLM class.
        """
        return self.llm

    def generate(self, prompt: str) -> str:
        """
        Generates output from Gemini 2.5 Flash model for the given prompt.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The generated output from the LLM.
        """
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        """
        Asynchronously generates output from Gemini 2.5 Flash Lite model for the given prompt.
        Uses the asynchronous `ainvoke` method of the underlying LLM.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The asynchronously generated output from the LLM.
        """
        return (await self.llm.ainvoke(prompt)).content