from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

llm = ChatOpenAI(
    model="qwen-local",
    openai_api_base="http://127.0.0.1:8080/v1",
    openai_api_key="none"
)

def multiply(a: int, b: int) -> int:
    """Multiply a and b.

    Args:
        a: first int
        b: second int
    """
    return a * b

tools = [multiply]

llm_with_tools = llm.bind_tools(tools)

sys_msg = SystemMessage(content="You are a helpful assistant tasked with performing arithmetic on a set of inputs.")

result = llm_with_tools.invoke([sys_msg]+[HumanMessage(content="Multipy 2 and 4")])
print(result.content)

# print(llm.invoke("multipy 2 and 4").content)

