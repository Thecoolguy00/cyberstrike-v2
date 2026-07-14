from langchain_openrouter import ChatOpenRouter
from langchain_core.language_models.chat_models import BaseChatModel
from app.services.llm_services.llm_interface import LLMInterface
from app.utilities.singletons_factory import DcSingleton
from dotenv import load_dotenv
import os

load_dotenv()

openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip('"\'')
openrouter_base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip('"\'')


def _build_reasoning_config(reasoning_effort: str | None) -> dict | None:
    if reasoning_effort is None:
        return None
    reasoning: dict[str, object] = {}
    if reasoning_effort is not None:
        reasoning["effort"] = reasoning_effort
    return reasoning


class DeepseekV4FlashOpenRouterLLM(LLMInterface, metaclass=DcSingleton):
    def __init__(
        self,
        temperature: float = 0.5,
        rate_limiter=None,
        streaming: bool = True,
        reasoning_effort: str | None = "low",
    ):
        reasoning = _build_reasoning_config(reasoning_effort)
        self.llm = ChatOpenRouter(
            model="deepseek/deepseek-v4-flash",
            api_key=openrouter_key,
            base_url=openrouter_base_url,
            temperature=temperature,
            rate_limiter=rate_limiter,
            streaming=streaming,
            reasoning=reasoning
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
        streaming: bool = True,
        reasoning_effort: str | None = "medium",
    ):
        reasoning = _build_reasoning_config(reasoning_effort)
        self.llm = ChatOpenRouter(
            model="deepseek/deepseek-v4-pro",
            api_key=openrouter_key,
            base_url=openrouter_base_url,
            temperature=temperature,
            rate_limiter=rate_limiter,
            streaming=streaming,
            reasoning=reasoning
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
        streaming: bool = True,
        reasoning_effort: str | None = "low",
    ):
        reasoning = _build_reasoning_config(reasoning_effort)
        self.llm = ChatOpenRouter(
            model="tencent/hy3-preview",
            api_key=openrouter_key,
            base_url=openrouter_base_url,
            temperature=temperature,
            rate_limiter=rate_limiter,
            streaming=streaming,
            reasoning=reasoning
        )

    def get_llm(self) -> BaseChatModel:
        return self.llm

    def generate(self, prompt: str) -> str:
        return self.llm.invoke(prompt).content

    async def agenerate(self, prompt: str) -> str:
        return (await self.llm.ainvoke(prompt)).content
