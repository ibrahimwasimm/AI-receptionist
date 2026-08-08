"""
generate_female_urdu_fillers_openai.py
======================================
Uses OpenAI tts-1 (voice="nova" - female) to generate 24kHz PCM directly,
resamples 24kHz -> 8kHz using audioop, converts to mulaw, and outputs Base64 strings.
"""
import os
import base64
import audioop
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

def generate_urdu_filler(text: str, filename: str):
    if not OPENAI_API_KEY:
        print("[FAIL] OPENAI_API_KEY not found in .env")
        return None
        
    client = OpenAI(api_key=OPENAI_API_KEY)
    print(f"Generating female Urdu voice for: '{text}'...")
    
    response = client.audio.speech.create(
        model="tts-1",
        voice="nova",  # Warm female voice
        input=text,
        response_format="pcm"  # 24kHz 16-bit PCM mono
    )
    
    pcm_24k = response.content
    
    # 24kHz -> 8kHz resample
    pcm_8k, _ = audioop.ratecv(pcm_24k, 2, 1, 24000, 8000, None)
    
    # 16-bit linear PCM -> 8-bit mulaw
    mulaw_bytes = audioop.lin2ulaw(pcm_8k, 2)
    b64 = base64.b64encode(mulaw_bytes).decode("utf-8")
    
    print(f"[SUCCESS] {filename} ('{text}'): {len(b64)} b64 chars")
    return b64

if __name__ == "__main__":
    b64_checking = generate_urdu_filler("جی، ایک سیکنڈ میں چیک کرتی ہوں۔", "verbal_checking")
    b64_booking  = generate_urdu_filler("جی، میں آپ کا اپائنٹمنٹ بک کر رہی ہوں۔", "verbal_booking")
    b64_general  = generate_urdu_filler("اچھا، ایک سیکنڈ...", "verbal_general")
    
    print("\n--- BASE64 FEMALE URDU VERBAL FILLERS ---")
    print(f"VERBAL_FILLER_CHECKING = \"{b64_checking}\"")
    print(f"VERBAL_FILLER_BOOKING  = \"{b64_booking}\"")
    print(f"VERBAL_FILLER_GENERAL  = \"{b64_general}\"")
