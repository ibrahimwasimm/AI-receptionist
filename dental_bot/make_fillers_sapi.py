"""
make_fillers_sapi.py
====================
Uses built-in Windows SAPI / PowerShell SpeechSynthesizer to generate WAV files,
resample to 8kHz, convert to mulaw, and print Base64 strings.
"""
import os
import wave
import audioop
import base64
import subprocess

def create_sapi_filler(text: str, filename: str):
    wav_path = f"{filename}_temp.wav"
    
    # PowerShell command using SAPI.SpVoice to record to WAV file
    ps_script = f"""
$Voice = New-Object -ComObject SAPI.SpVoice
$Stream = New-Object -ComObject SAPI.SpFileStream
$Stream.Open('{wav_path}', 3, $false)
$Voice.AudioOutputStream = $Stream
$Voice.Speak('{text}')
$Stream.Close()
"""
    ps_file = f"{filename}.ps1"
    with open(ps_file, "w", encoding="utf-8") as f:
        f.write(ps_script)

    subprocess.run(f"powershell -ExecutionPolicy Bypass -File {ps_file}", shell=True)
    if os.path.exists(ps_file):
        os.remove(ps_file)

    if not os.path.exists(wav_path):
        print(f"[FAIL] WAV file not created: {wav_path}")
        return None

    # Read WAV and resample to 8kHz 16-bit mono
    with wave.open(wav_path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth  = wf.getsampwidth()
        framerate  = wf.getframerate()
        frames     = wf.readframes(wf.getnframes())

    # If stereo -> mono
    if n_channels == 2:
        frames = audioop.tomono(frames, sampwidth, 1, 1)

    # Resample to 8000 Hz
    pcm_8k, _ = audioop.ratecv(frames, sampwidth, 1, framerate, 8000, None)

    # Convert 16-bit linear PCM -> 8-bit mulaw
    mulaw_bytes = audioop.lin2ulaw(pcm_8k, sampwidth)
    b64 = base64.b64encode(mulaw_bytes).decode("utf-8")

    if os.path.exists(wav_path):
        os.remove(wav_path)

    print(f"[SUCCESS] {filename}: {len(b64)} chars")
    return b64

if __name__ == "__main__":
    b64_checking = create_sapi_filler("One second, checking the calendar.", "filler_checking")
    b64_booking  = create_sapi_filler("One moment, booking your appointment.", "filler_booking")
    
    print("\n--- BASE64 STRINGS ---")
    print(f"FILLER_CHECKING = \"{b64_checking}\"")
    print(f"FILLER_BOOKING  = \"{b64_booking}\"")
