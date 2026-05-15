import requests

res = requests.get("https://openrouter.ai/api/v1/models")
if res.status_code == 200:
    models = res.json().get("data", [])
    free_models = [m["id"] for m in models if "free" in m["id"].lower()]
    print(free_models)
