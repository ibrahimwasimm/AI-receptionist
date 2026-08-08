"""
make_filler_chime.py
====================
Generates a soft, pleasant acoustic processing chime (µ-law 8kHz Base64)
using pure Python math (no external dependencies needed!).
"""
import math
import struct
import audioop
import base64

def generate_soft_chime():
    sample_rate = 8000
    duration = 0.35  # seconds
    n_samples = int(sample_rate * duration)
    
    pcm_bytes = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        # Soft dual tone (440Hz A4 + 659.25Hz E5 - major fifth interval, pleasant chime)
        # Apply exponential decay envelope for soft acoustic feel
        envelope = math.exp(-i / (sample_rate * 0.12))
        signal = 0.3 * (math.sin(2 * math.pi * 440 * t) + math.sin(2 * math.pi * 659.25 * t)) * envelope
        # Scale to 16-bit PCM integer
        sample_val = int(signal * 32767)
        sample_val = max(-32768, min(32767, sample_val))
        pcm_bytes.extend(struct.pack("<h", sample_val))

    mulaw_bytes = audioop.lin2ulaw(bytes(pcm_bytes), 2)
    b64_str = base64.b64encode(mulaw_bytes).decode("utf-8")
    print(f"CHIME_B64 = \"{b64_str}\"")
    return b64_str

if __name__ == "__main__":
    generate_soft_chime()
