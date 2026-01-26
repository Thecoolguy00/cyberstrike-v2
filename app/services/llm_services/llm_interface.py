from abc import abstractmethod
from app.utilities.singletons_factory import DcSingleton
from langchain_core.language_models.chat_models import BaseChatModel

class LLMInterface( metaclass=DcSingleton):
    
    @abstractmethod
    def __init__(self) -> None:
        pass
    
    @abstractmethod
    def get_llm(self) -> BaseChatModel:
        pass
    
    @abstractmethod
    def generate(self) -> str:
        pass

    @abstractmethod
    async def agenerate(self) -> str:
        pass