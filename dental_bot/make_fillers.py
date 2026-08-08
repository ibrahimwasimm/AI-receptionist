"""
make_fillers.py
===============
Generate base64 µ-law 8kHz audio strings for instant tool-execution audio fillers.
"""
import base64
import audioop
import io
import asyncio
from gtts import gTTS
import pydub # if available, or wave

async def create_filler(text: str, filename: str):
    try:
        from gtts import gTTS
        import subprocess

        print(f"Generating audio for: '{text}'...")
        tts = gTTS(text=text, lang="ur")
        mp3_path = f"{filename}.mp3"
        wav_path = f"{filename}.wav"
        tts.save(mp3_path)

        # Convert MP3 to 8kHz mono WAV using ffmpeg if available or wave
        cmd = f'ffmpeg -y -i "{mp3_path}" -ar 8000 -ac 1 -f s16le "{wav_path}"'
        res = subprocess.run(cmd, shell=True, capture_output=True)
        
        if res.returncode == 0 and os.path.exists(wav_path):
            with open(wav_path, "rb") as f:
                pcm_8k = f.read()
            mulaw = audioop.lin2ulaw(pcm_8k, 2)
            b64 = base64.b64encode(mulaw).decode("utf-8")
            print(f"[SUCCESS] Generated {filename}: {len(b64)} b64 chars")
            return b64
        else:
            print(f"[WARN] ffmpeg conversion failed: {res.stderr.decode()}")
            return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None

if __name__ == "__main__":
    import os
    asyncio.run(create_filler("Ji, ek second main check karti hoon.", "filler_checking"))
    asyncio.run(create_filler("Ji, main aap ka appointment book kar rahi hoon.", "filler_booking"))
