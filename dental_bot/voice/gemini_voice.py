"""
gemini_voice.py — Gemini 2.0 Flash Live API handler
=====================================================
Manages a single Gemini Live session for one phone call.

Usage (async context manager):
    async with GeminiVoiceHandler() as gemini:
        await gemini.send_audio(pcm_16khz_bytes)
        async for kind, data in gemini.receive():
            if kind == "audio":    ...  # PCM 24kHz bytes
            if kind == "transcript": ...  # patient's speech text
            if kind == "bot_text":   ...  # bot's speech text

Audio formats:
  Input  → PCM 16-bit 16kHz mono (converted from Twilio µ-law 8kHz)
  Output → PCM 16-bit 24kHz mono (must be converted to Twilio µ-law 8kHz)
"""

import logging
import os
from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types

logger = logging.getLogger("voice.gemini")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CLINIC_NAME    = os.getenv("CLINIC_NAME", "Dental Clinic")

_SYSTEM_PROMPT = f"""You are Sara, a professional and caring voice receptionist \
at {CLINIC_NAME} in Karachi, Pakistan.

══ LANGUAGE ══
Detect patient language automatically.
Urdu speaker → respond fully in Urdu.
English speaker → respond fully in English.
Mixed → match naturally.
Roman Urdu is perfectly fine.

══ GREETING — say this ONCE when call connects ══
Urdu:    Assalam o Alaikum! {CLINIC_NAME} mein khush aamdeed. \
Main Sara hoon. Aap ki kaise madad kar sakti hoon?
English: Hello, welcome to {CLINIC_NAME}. \
This is Sara. How can I help you today?

══ SERVICES YOU HANDLE ══
• Appointment booking   — collect name, contact number, dental issue, date, time
• Appointment cancellation and rescheduling
• Clinic hours and location information
• Services offered: cleaning, filling, extraction, root canal, braces, \
whitening, crowns, implants, dentures, pediatric dentistry, x-rays
• Consultation fees and payment methods
• General dental hygiene advice

══ APPOINTMENT BOOKING FLOW ══
1. Ask for full name
2. Ask for contact number
3. Ask what dental issue they are facing
4. Ask for preferred date
5. Ask for preferred time
6. Confirm all details back to the patient
7. Say "appointment noted and will be confirmed before your visit"

══ EMERGENCY RESPONSE ══
If the patient describes ANY of these: severe pain, knocked out tooth, \
broken jaw, heavy bleeding, severe swelling, abscess, cannot open mouth, \
unbearable pain, shadeed dard, dant toot gaya, jabra toot gaya, munh se khoon:

Urdu:    Yeh emergency lagti hai. Rukiye, main aapko abhi dentist se \
connect karti hoon. Please hold karein.
English: This sounds urgent. Please hold while I connect you to the \
dentist immediately.

Then stop speaking and wait silently — the system will handle the transfer.

══ STRICT RULES ══
• Never diagnose medical conditions
• Never prescribe medications or dosages
• Keep responses SHORT — maximum 2 to 3 sentences per reply
• This is a phone call, not a chat — speak naturally, conversationally
• No bullet points or numbered lists in your speech
• Do not mention you are an AI — you are Sara the receptionist
"""


class GeminiVoiceHandler:
    """
    Async context manager that owns one Gemini Live session per call.
    """

    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in .env")
        self._client  = genai.Client(api_key=GEMINI_API_KEY)
        self._session = None
        self._cm      = None   # the live.connect() context manager

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "GeminiVoiceHandler":
        config = self._build_config()
        self._cm      = self._client.aio.live.connect(
            model  = "gemini-2.5-flash-native-audio-latest",
            config = config,
        )
        self._session = await self._cm.__aenter__()
        logger.info("[Gemini] Live session opened")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._cm:
            try:
                await self._cm.__aexit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                logger.warning(f"[Gemini] Session close warning: {e}")
        logger.info("[Gemini] Live session closed")

    # ── Public interface ──────────────────────────────────────────────────────

    async def send_audio(self, pcm_16khz_bytes: bytes) -> None:
        """Forward patient audio (PCM 16-bit 16kHz mono) to Gemini."""
        if self._session is None:
            return
        try:
            await self._session.send_realtime_input(
                audio=types.Blob(
                    data      = pcm_16khz_bytes,
                    mime_type = "audio/pcm;rate=16000",
                )
            )
        except Exception as e:
            logger.error(f"[Gemini] send_audio error: {e}")

    async def receive(self):
        """
        Async generator — yields (kind, data) tuples from the Gemini session.

        Kinds:
          "audio"      → bytes (PCM 24kHz 16-bit mono)  → send to Twilio
          "transcript" → str  (patient's speech)         → check for emergency
          "bot_text"   → str  (bot's own speech text)    → for logging
        """
        if self._session is None:
            return

        try:
            async for response in self._session.receive():
                # ── Bot audio response ─────────────────────────────────────
                if response.data is not None:
                    yield ("audio", response.data)

                # ── Transcriptions ─────────────────────────────────────────
                if hasattr(response, "server_content") and response.server_content:
                    sc = response.server_content

                    # Patient's spoken words (input transcription)
                    if (hasattr(sc, "input_transcription")
                            and sc.input_transcription
                            and sc.input_transcription.text):
                        yield ("transcript", sc.input_transcription.text)

                    # Bot's spoken words (output transcription — for logs only)
                    if (hasattr(sc, "output_transcription")
                            and sc.output_transcription
                            and sc.output_transcription.text):
                        yield ("bot_text", sc.output_transcription.text)

                # Fallback: response.text covers model turn text (older SDK behaviour)
                elif response.text:
                    yield ("bot_text", response.text)

        except Exception as e:
            # Surface connection errors gracefully — caller decides what to do
            logger.error(f"[Gemini] receive error: {e}")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription   = types.AudioTranscriptionConfig(),
            output_audio_transcription  = types.AudioTranscriptionConfig(),
            speech_config               = types.SpeechConfig(
                voice_config = types.VoiceConfig(
                    prebuilt_voice_config = types.PrebuiltVoiceConfig(
                        voice_name = "Aoede"   # warm bilingual voice
                    )
                )
            ),
            system_instruction = _SYSTEM_PROMPT,
        )
