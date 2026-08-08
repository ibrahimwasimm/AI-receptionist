"""
generate_female_urdu_fillers.py
================================
Generates high quality female Urdu verbal fillers using gTTS / edge-tts / openai,
resamples to 8kHz 16-bit PCM, converts to mulaw, and outputs Base64 strings.
"""
import os
import sys
import base64
import audioop
import subprocess

def install_and_import():
    try:
        import gtts
    except ImportError:
        print("Installing gTTS...")
        subprocess.run(f'"{sys.executable}" -m pip install gtts', shell=True)

install_and_import()
from gtts import gTTS

def text_to_mulaw_b64(text: str, filename: str):
    mp3_file = f"{filename}.mp3"
    wav_file = f"{filename}.wav"
    
    tts = gTTS(text=text, lang="ur")
    tts.save(mp3_file)
    
    # Use ffmpeg or python wav conversion
    cmd = f'ffmpeg -y -i "{mp3_file}" -ar 8000 -ac 1 -c:a pcm_s16le "{wav_file}"'
    res = subprocess.run(cmd, shell=True, capture_output=True)
    
    if res.returncode != 0 or not os.path.exists(wav_file):
        print(f"[FAIL] ffmpeg error: {res.stderr.decode()}")
        return None
        
    with open(wav_file, "rb") as f:
        # Skip 44-byte WAV header
        f.seek(44)
        pcm_8k = f.read()
        
    mulaw = audioop.lin2ulaw(pcm_8k, 2)
    b64 = base64.b64encode(mulaw).decode("utf-8")
    
    # Clean up temp files
    if os.path.exists(mp3_file): os.remove(mp3_file)
    if os.path.exists(wav_file): os.remove(wav_file)
    
    print(f"[SUCCESS] {filename} ('{text}'): {len(b64)} b64 chars")
    return b64

if __name__ == "__main__":
    b64_checking = text_to_mulaw_b64("جی، ایک سیکنڈ میں چیک کرتی ہوں۔", "verbal_checking")
    b64_booking  = text_to_mulaw_b64("جی، میں آپ کا اپائنٹمنٹ بک کر رہی ہوں۔", "verbal_booking")
    b64_general  = text_to_mulaw_b64("اچھا، ایک سیکنڈ...", "verbal_general")
    
    print("\n--- BASE64 FEMALE URDU FILLERS ---")
    print(f"VERBAL_FILLER_CHECKING = \"{b64_checking}\"")
    print(f"VERBAL_FILLER_BOOKING  = \"{b64_booking}\"")
    print(f"VERBAL_FILLER_GENERAL  = \"{b64_general}\"")
