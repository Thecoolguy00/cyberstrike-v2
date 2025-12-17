from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
import os

load_dotenv()
api_key=os.getenv("GOOGLE_API_KEY","")

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash",api_key=api_key)

response = llm.invoke("Who are you")
print(response.content)


