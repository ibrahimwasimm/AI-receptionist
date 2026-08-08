"""
test_live_api.py
================
Diagnose whether your Gemini API key has Live API (bidiGenerateContent) access.

Run with:
    venv\Scripts\python.exe test_live_api.py
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

async def test_live_v1beta():
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        async with client.aio.live.connect(model="gemini-2.5-flash-native-audio-latest") as session:
            print("[v1beta] gemini-2.5-flash-native-audio-latest -> CONNECTED SUCCESSFULLY!")
            return True
    except Exception as e:
        print(f"[v1beta] gemini-2.5-flash-native-audio-latest -> FAILED: {e}")
        return False

async def test_live_v1alpha():
    from google import genai
    from google.genai.types import HttpOptions
    client = genai.Client(api_key=GEMINI_API_KEY, http_options=HttpOptions(api_version="v1alpha"))
    try:
        async with client.aio.live.connect(model="gemini-2.0-flash-exp") as session:
            print("[v1alpha] gemini-2.0-flash-exp -> CONNECTED!")
            return True
    except Exception as e:
        print(f"[v1alpha] gemini-2.0-flash-exp -> FAILED: {e}")
        return False

async def test_regular_api():
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    for model in ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]:
        try:
            response = client.models.generate_content(
                model=model,
                contents="Say hello in one word."
            )
            print(f"[REST API] {model} -> WORKS: {response.text.strip()}")
            return True
        except Exception as e:
            err = str(e)[:120]
            print(f"[REST API] {model} -> FAILED: {err}")
    return False

async def main():
    print("=" * 60)
    print("Gemini Live API Diagnostic")
    print("=" * 60)
    print(f"API Key: {GEMINI_API_KEY[:10]}...{GEMINI_API_KEY[-6:]}\n")

    # Test 1: Regular REST API (should always work if key is valid)
    rest_ok = await test_regular_api()

    # Test 2: Live API v1beta
    print()
    v1beta_ok = await test_live_v1beta()

    # Test 3: Live API v1alpha
    print()
    v1alpha_ok = await test_live_v1alpha()

    # Summary
    print("\n" + "=" * 60)
    print("RESULT SUMMARY")
    print("=" * 60)
    if not rest_ok:
        print("-> API key is INVALID or has no Gemini access at all.")
    elif not v1beta_ok and not v1alpha_ok:
        print("-> API key works for regular API but has NO Live API access.")
        print("")
        print("FIX OPTIONS:")
        print("1. Go to https://aistudio.google.com/apikey")
        print("   Create a new key and make sure 'Gemini Live API' is enabled.")
        print("2. Or switch to Deepgram+ElevenLabs pipeline (no Live API needed).")
    elif v1beta_ok:
        print("-> Live API works on v1beta! Use model: gemini-2.0-flash-live-001")
    elif v1alpha_ok:
        print("-> Live API works on v1alpha! Use model: gemini-2.0-flash-exp")

asyncio.run(main())
