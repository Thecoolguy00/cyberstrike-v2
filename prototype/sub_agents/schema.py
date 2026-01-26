from typing import Annotated, List
import operator
from langgraph.graph import MessagesState

class BaseState(MessagesState):
    tool_used:Annotated[List[str],operator.add]
    task:str