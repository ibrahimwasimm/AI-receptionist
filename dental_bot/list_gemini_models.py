"""
list_gemini_models.py
"""
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

client = genai.Client(api_key=GEMINI_API_KEY)
print("Querying models from Google GenAI API...")
for m in client.models.list():
    if "flash" in m.name.lower() or "live" in m.name.lower() or "audio" in m.name.lower():
        print(f"Model ID: {m.name} | Display Name: {m.display_name}")
