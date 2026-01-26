from abc import abstractmethod
from fastapi import status

class DcException(Exception):

    @abstractmethod
    def get_code(self):
        pass
    
    @abstractmethod
    def get_message(self):
        pass
class LLMFactoryException(Exception):
    def __init__(self,message: str=None) -> None:
        self.code = status.HTTP_406_NOT_ACCEPTABLE
        if message is None:
            self.message="Exception in LLM factory."
        else:
            self.message=message
    def get_code(self):
        return self.code
    
    def get_messsage(self):
        return self.message

class MissingEnvironmentVariableException(DcException):
    def __init__(self, variable_name: str) -> None:
        self.code = status.HTTP_500_INTERNAL_SERVER_ERROR
        self.message = f"Required environment variable '{variable_name}' is missing"
    
    def get_code(self):
        return self.code
    
    def get_message(self):
        return self.message

class MissingPromptException(DcException):
    def __init__(self, variable_name: str) -> None:
        self.code = status.HTTP_500_INTERNAL_SERVER_ERROR
        self.message = f"Required prompt: '{variable_name}' is missing"
    
    def get_code(self):
        return self.code
    
    def get_message(self):
        return self.message