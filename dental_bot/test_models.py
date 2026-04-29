import os
import requests
import re
from dotenv import load_dotenv

load_dotenv(override=True)
key = os.getenv('OPENROUTER_API_KEY')

print("Fetching models...")
data = requests.get('https://openrouter.ai/api/v1/models').json()['data']
free_models = [m['id'] for m in data if m['id'].endswith(':free')]

print(f"Testing {len(free_models)} free models...")
valid_model = None
for m in free_models:
    try:
        r = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={'Authorization': f'Bearer {key}'},
            json={'model': m, 'messages': [{'role': 'user', 'content': 'hi'}]}
        )
        if r.status_code == 200:
            valid_model = m
            break
    except Exception as e:
        continue

print(f"FOUND: {valid_model}")

if valid_model:
    with open('agent.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace the current model string with the working one
    updated = re.sub(r'model="[^"]+:free"', f'model="{valid_model}"', content)
    
    with open('agent.py', 'w', encoding='utf-8') as f:
        f.write(updated)
    print("Updated agent.py with working model!")
