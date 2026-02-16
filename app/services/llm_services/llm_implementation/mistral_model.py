from langchain_mistralai import ChatMistralAI
from langchain_core.language_models.chat_models import BaseChatModel
from app.services.llm_services.llm_interface import LLMInterface
from app.utilities.singletons_factory import DcSingleton
import os
from dotenv import load_dotenv

load_dotenv()

mistral_key = os.getenv("MISTRAL_API_KEY", "")


class MistralLargeLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(self, temperature: float = 0.0, max_retries: int = 2, rate_limiter=None):
        self.llm = ChatMistralAI(
            model="mistral-large-latest",
            api_key=mistral_key,
            temperature=temperature,
            max_retries=max_retries,
            rate_limiter=rate_limiter
        )

    def get_llm(self) -> BaseChatModel:
        return self.llm

    def generate(self, prompt: str) -> str:
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        return (await self.llm.ainvoke(prompt)).content
    
class MistralMediumLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(self, temperature: float = 0.0, max_retries: int = 2, rate_limiter=None):
        self.llm = ChatMistralAI(
            model="mistral-medium",
            api_key=mistral_key,
            temperature=temperature,
            max_retries=max_retries,
            rate_limiter=rate_limiter
        )

    def get_llm(self) -> BaseChatModel:
        return self.llm

    def generate(self, prompt: str) -> str:
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        return (await self.llm.ainvoke(prompt)).content
