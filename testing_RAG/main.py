from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from vector import retriever

model = ChatOpenAI(
    model="qwen-local",
    openai_api_base="http://127.0.0.1:8080/v1",
    openai_api_key="none",
    temperature=0.2
)

template = """
You are an helpdesk expert at answering technical questions

Question relevant data: {relevant_data}

Here is the question to answer: {question}
"""
prompt = ChatPromptTemplate.from_template(template)
chain = prompt | model

while True:
    print("\n\n-------------------------------")
    question = input("Ask your question (q to quit): ")
    print("\n\n")
    if question == "q":
        break
    
    relevant_data = retriever.invoke(question)
    print(relevant_data)
    result = chain.invoke({"relevant_data": relevant_data, "question": question})
    print(result.content)