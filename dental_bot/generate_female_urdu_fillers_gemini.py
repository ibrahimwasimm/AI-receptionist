"""
generate_female_urdu_fillers_gemini.py
======================================
Uses Gemini Live / REST API to generate female Urdu speech audio,
converts to mulaw 8kHz, and outputs Base64 strings.
"""
import os
import base64
import audioop
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

client = genai.Client(api_key=GEMINI_API_KEY)

def generate_urdu_filler_gemini(text: str, filename: str):
    print(f"Generating female Urdu voice via Gemini for: {filename}...")
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=f"Say exactly this phrase in female Urdu voice, output ONLY audio: {text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede"  # Female voice
                    )
                )
            )
        )
    )
    
    audio_bytes = None
    if hasattr(response, "candidates") and response.candidates:
        for cand in response.candidates:
            if hasattr(cand, "content") and cand.content and hasattr(cand.content, "parts"):
                for part in cand.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                        audio_bytes = part.inline_data.data
                        break
                        
    if not audio_bytes:
        print(f"[FAIL] No audio returned for {filename}")
        return None
        
    # Gemini audio is 24kHz PCM mono 16-bit
    pcm_8k, _ = audioop.ratecv(audio_bytes, 2, 1, 24000, 8000, None)
    mulaw_bytes = audioop.lin2ulaw(pcm_8k, 2)
    b64 = base64.b64encode(mulaw_bytes).decode("utf-8")
    
    print(f"[SUCCESS] {filename}: {len(b64)} b64 chars")
    return b64

if __name__ == "__main__":
    b64_checking = generate_urdu_filler_gemini("جی، ایک سیکنڈ میں چیک کرتی ہوں۔", "verbal_checking")
    b64_booking  = generate_urdu_filler_gemini("جی، میں آپ کا اپائنٹمنٹ بک کر رہی ہوں۔", "verbal_booking")
    b64_general  = generate_urdu_filler_gemini("اچھا، ایک سیکنڈ...", "verbal_general")
    
    with open("female_verbal_fillers.py", "w", encoding="utf-8") as f:
        f.write(f'VERBAL_FILLER_CHECKING = "{b64_checking}"\n\n')
        f.write(f'VERBAL_FILLER_BOOKING  = "{b64_booking}"\n\n')
        f.write(f'VERBAL_FILLER_GENERAL  = "{b64_general}"\n')
    print("Wrote female_verbal_fillers.py successfully!")
