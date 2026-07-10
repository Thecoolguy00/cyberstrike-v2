from langchain_openrouter import ChatOpenRouter
from langchain_core.language_models.chat_models import BaseChatModel
from app.services.llm_services.llm_interface import LLMInterface
from app.utilities.singletons_factory import DcSingleton
from dotenv import load_dotenv
import os

load_dotenv()

openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
openrouter_base_url = "https://openrouter.ai/api/v1"

class DeepseekV4FlashOpenRouterLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(
        self,
        temperature: float = 0.5,
        rate_limiter=None,
    ):
        self.llm = ChatOpenRouter(
            model="deepseek/deepseek-v4-flash",
            api_key=openrouter_key,
            base_url=openrouter_base_url,
            temperature=temperature,
            rate_limiter=rate_limiter,
            reasoning={"effort":"medium"}
        )

    def get_llm(self) -> BaseChatModel:
        return self.llm

    def generate(self, prompt: str) -> str:
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        return (await self.llm.ainvoke(prompt)).content
    

class DeepseekV4ProOpenRouterLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(
        self,
        temperature: float = 0.5,
        rate_limiter=None,
    ):
        self.llm = ChatOpenRouter(
            model="deepseek/deepseek-v4-pro",
            api_key=openrouter_key,
            base_url=openrouter_base_url,
            temperature=temperature,
            rate_limiter=rate_limiter,
            reasoning={"effort":"medium"}
        )

    def get_llm(self) -> BaseChatModel:
        return self.llm

    def generate(self, prompt: str) -> str:
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        return (await self.llm.ainvoke(prompt)).content


class TencentHy3PreviewOpenRouterLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(
        self,
        temperature: float = 0.5,
        rate_limiter=None,
    ):
        self.llm = ChatOpenRouter(
            model="tencent/hy3-preview",
            api_key=openrouter_key,
            base_url=openrouter_base_url,
            temperature=temperature,
            rate_limiter=rate_limiter,
            reasoning={"effort":"low"}
        )

    def get_llm(self) -> BaseChatModel:
        return self.llm

    def generate(self, prompt: str) -> str:
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        return (await self.llm.ainvoke(prompt)).content
