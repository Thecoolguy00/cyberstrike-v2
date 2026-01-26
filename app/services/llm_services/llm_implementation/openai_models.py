from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

from langchain_core.language_models.chat_models import BaseChatModel
from app.services.llm_services.llm_interface import LLMInterface
from app.utilities.singletons_factory import DcSingleton

load_dotenv()


class GPT4oLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(self, temperature: float = 1.0, rate_limiter=None):
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=temperature,
            rate_limiter=rate_limiter
        )

    def get_llm(self) -> BaseChatModel:
        """
        Static method to get an instance of GPT4oLLM.

        Returns:
            GPT4oLLM: An instance of the GPT4oLLM class.
        """
        return self.llm

    def generate(self, prompt: str) -> str:
        """
        Generates output from GPT-4o model for the given prompt.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The generated output from the LLM.
        """
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        """
        Asynchronously generates output from GPT-4o model for the given prompt.
        Uses the asynchronous `ainvoke` method of the underlying LLM.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The asynchronously generated output from the LLM.
        """
        return (await self.llm.ainvoke(prompt)).content


class GPT4oMiniLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(self, temperature: float = 1.0, rate_limiter=None):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=temperature,
            rate_limiter=rate_limiter
        )

    def get_llm(self) -> BaseChatModel:
        """
        Static method to get an instance of GPT4oMiniLLM.

        Returns:
            GPT4oMiniLLM: An instance of the GPT4oMiniLLM class.
        """
        return self.llm

    def generate(self, prompt: str) -> str:
        """
        Generates output from GPT-4o-mini model for the given prompt.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The generated output from the LLM.
        """
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        """
        Asynchronously generates output from GPT-4o-mini model for the given prompt.
        Uses the asynchronous `ainvoke` method of the underlying LLM.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The asynchronously generated output from the LLM.
        """
        return (await self.llm.ainvoke(prompt)).content


class O1PreviewLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(self, temperature: float = 1.0):
        self.llm = ChatOpenAI(
            model="o1-preview",
            temperature=temperature
        )

    def get_llm(self) -> BaseChatModel:
        """
        Static method to get an instance of O1PreviewLLM.

        Returns:
            O1PreviewLLM: An instance of the O1PreviewLLM class.
        """
        return self.llm

    def generate(self, prompt: str) -> str:
        """
        Generates output from O1-preview model for the given prompt.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The generated output from the LLM.
        """
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        """
        Asynchronously generates output from O1-preview model for the given prompt.
        Uses the asynchronous `ainvoke` method of the underlying LLM.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The asynchronously generated output from the LLM.
        """
        return (await self.llm.ainvoke(prompt)).content


class O1MiniLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(self, temperature: float = 1.0):
        self.llm = ChatOpenAI(
            model="o1-mini",
            temperature=temperature
        )

    def get_llm(self) -> BaseChatModel:
        """
        Static method to get an instance of O1MiniLLM.

        Returns:
            O1MiniLLM: An instance of the O1MiniLLM class.
        """
        return self.llm

    def generate(self, prompt: str) -> str:
        """
        Generates output from O1-mini model for the given prompt.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The generated output from the LLM.
        """
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        """
        Asynchronously generates output from O1-mini model for the given prompt.
        Uses the asynchronous `ainvoke` method of the underlying LLM.

        Args:
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The asynchronously generated output from the LLM.
        """
        return (await self.llm.ainvoke(prompt)).content
