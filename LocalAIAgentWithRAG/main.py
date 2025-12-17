from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from vector import retriever

model = ChatOpenAI(
    model="local-llama",
    openai_api_base="http://127.0.0.1:8080/v1",
    openai_api_key="none"
)

template = """
You are an expert in answering questions about a pizza restaurant

Here are some relevant reviews: {reviews}

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
    
    reviews = retriever.invoke(question)
    print(reviews)
    result = chain.invoke({"reviews": reviews, "question": question})
    print(result.content)