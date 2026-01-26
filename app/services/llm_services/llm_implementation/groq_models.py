from langchain_groq import ChatGroq
from langchain_core.language_models.chat_models import BaseChatModel
from app.services.llm_services.llm_interface import LLMInterface
from app.utilities.singletons_factory import DcSingleton
import os
from dotenv import load_dotenv

load_dotenv()

groq_key = os.getenv("GROQ_API_KEY", "")


class Llama3GroqLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(self, temperature: float = 0.5, rate_limiter=None):
        self.llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=groq_key,
            temperature=temperature,
            rate_limiter=rate_limiter
        )

    def get_llm(self) -> BaseChatModel:
        return self.llm

    def generate(self, prompt: str) -> str:
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        return (await self.llm.ainvoke(prompt)).content


class MoonshotKimiGroqLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(self, temperature: float = 0.5, rate_limiter=None):
        self.llm = ChatGroq(
            model="moonshotai/kimi-k2-instruct-0905",
            api_key=groq_key,
            temperature=temperature,
            rate_limiter=rate_limiter
        )

    def get_llm(self) -> BaseChatModel:
        return self.llm

    def generate(self, prompt: str) -> str:
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        return (await self.llm.ainvoke(prompt)).content


class GPTOSS120bGroqLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(self, temperature: float = 0.5, rate_limiter=None):
        self.llm = ChatGroq(
            model="openai/gpt-oss-120b",
            api_key=groq_key,
            temperature=temperature,
            rate_limiter=rate_limiter
        )

    def get_llm(self) -> BaseChatModel:
        return self.llm

    def generate(self, prompt: str) -> str:
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        return (await self.llm.ainvoke(prompt)).content