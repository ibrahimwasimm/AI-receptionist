"""
test_step2_live.py
-------------------
Test script for STEP 2: Call Gemini Live API with gemini-2.5-flash-native-audio-latest,
send a short test message, and print the raw output / response.
"""
import asyncio
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

async def test_live_step2():
    print(f"Testing API Key: {GEMINI_API_KEY[:10]}...{GEMINI_API_KEY[-6:]}")
    print("Connecting to model: gemini-2.5-flash-native-audio-latest ...")
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    
    try:
        async with client.aio.live.connect(model="gemini-2.5-flash-native-audio-latest", config=config) as session:
            print("[SUCCESS] Session connected successfully!")
            
            # Send short test message
            print("Sending text prompt to Live session...")
            await session.send_client_content(
                turns=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Hello, state your model name in one sentence.")]
                    )
                ],
                turn_complete=True
            )
            
            # Receive response
            async for response in session.receive():
                if hasattr(response, "server_content") and response.server_content:
                    sc = response.server_content
                    if hasattr(sc, "model_turn") and sc.model_turn and hasattr(sc.model_turn, "parts"):
                        for part in sc.model_turn.parts:
                            if hasattr(part, "text") and part.text:
                                print(f"[RECEIVED TEXT]: {part.text}")
                    if hasattr(sc, "output_transcription") and sc.output_transcription and sc.output_transcription.text:
                        print(f"[RECEIVED TRANSCRIPTION]: {sc.output_transcription.text}")
                    if hasattr(sc, "turn_complete") and sc.turn_complete:
                        print("[TURN COMPLETE]")
                        break
    except Exception as e:
        print(f"[ERROR]: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test_live_step2())
