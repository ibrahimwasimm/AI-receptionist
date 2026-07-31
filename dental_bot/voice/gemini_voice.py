"""
gemini_voice.py — Gemini 2.0 Flash Live API handler
=====================================================
Manages a single Gemini Live session for one phone call.

Usage (async context manager):
    async with GeminiVoiceHandler() as gemini:
        await gemini.send_audio(pcm_16khz_bytes)
        async for kind, data in gemini.receive():
            if kind == "audio":      ...  # PCM 24kHz bytes
            if kind == "transcript": ...  # patient's speech text
            if kind == "bot_text":   ...  # bot's speech text

Audio formats:
  Input  -> PCM 16-bit 16kHz mono (converted from Twilio mu-law 8kHz)
  Output -> PCM 16-bit 24kHz mono (must be converted to Twilio mu-law 8kHz)

Resilience:
  - Circuit breaker on send_audio: stops after MAX_SEND_ERRORS consecutive failures
  - Exponential backoff between retries (0.1s -> 0.2s -> 0.4s)
  - Session-dead flag prevents any send after a fatal session error
  - Error logging is rate-limited (only logs first error per burst)
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types
from google.genai.types import HttpOptions

logger = logging.getLogger("voice.gemini")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CLINIC_NAME    = os.getenv("CLINIC_NAME", "Dental Clinic")

# Gemini Live model — must support bidiGenerateContent
# gemini-2.0-flash-exp is the correct model for the v1alpha Live API endpoint.
# The v1beta endpoint (SDK default) returns 1008 for most free-tier keys.
LIVE_MODEL  = "gemini-2.0-flash-exp"
LIVE_API_VER = "v1alpha"  # bidiGenerateContent is accessible via v1alpha

# Circuit breaker: stop retrying send_audio after this many consecutive failures
MAX_SEND_ERRORS  = 3
# Base backoff in seconds (doubles each retry: 0.1 -> 0.2 -> 0.4)
BASE_BACKOFF_SEC = 0.1

_SYSTEM_PROMPT = f"""You are Sara, a professional and caring voice receptionist \
at {CLINIC_NAME} in Karachi, Pakistan.

LANGUAGE:
Detect patient language automatically.
Urdu speaker - respond fully in Urdu.
English speaker - respond fully in English.
Mixed - match naturally.
Roman Urdu is perfectly fine.

GREETING - say this ONCE when call connects:
Urdu:    Assalam o Alaikum! {CLINIC_NAME} mein khush aamdeed. \
Main Sara hoon. Aap ki kaise madad kar sakti hoon?
English: Hello, welcome to {CLINIC_NAME}. \
This is Sara. How can I help you today?

SERVICES YOU HANDLE:
- Appointment booking: collect name, contact number, dental issue, date, time
- Appointment cancellation and rescheduling
- Clinic hours and location information
- Services: cleaning, filling, extraction, root canal, braces, whitening, \
crowns, implants, dentures, pediatric dentistry, x-rays
- Consultation fees and payment methods
- General dental hygiene advice

APPOINTMENT BOOKING FLOW:
1. Ask for full name
2. Ask for contact number
3. Ask what dental issue they are facing
4. Ask for preferred date
5. Ask for preferred time
6. Confirm all details back to the patient
7. Say appointment noted and will be confirmed before their visit

EMERGENCY RESPONSE:
If the patient describes severe pain, knocked out tooth, broken jaw, heavy bleeding, \
severe swelling, abscess, cannot open mouth, unbearable pain, shadeed dard, \
dant toot gaya, jabra toot gaya, munh se khoon:

Urdu:    Yeh emergency lagti hai. Rukiye, main aapko abhi dentist se \
connect karti hoon. Please hold karein.
English: This sounds urgent. Please hold while I connect you to the \
dentist immediately.

Then stop speaking and wait silently - the system will handle the transfer.

STRICT RULES:
- Never diagnose medical conditions
- Never prescribe medications or dosages
- Keep responses SHORT: maximum 2 to 3 sentences per reply
- This is a phone call, not a chat - speak naturally, conversationally
- No bullet points or numbered lists in your speech
- Do not mention you are an AI - you are Sara the receptionist
"""


class GeminiVoiceHandler:
    """
    Async context manager that owns one Gemini Live session per call.

    Resilience features:
      - _session_dead: set True on any fatal session error.
        All send_audio calls are silently dropped once dead.
      - _send_error_count: consecutive send failures.
        After MAX_SEND_ERRORS, session is marked dead and send is abandoned.
      - Exponential backoff between retries inside send_audio.
    """

    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in .env")
        # Use v1alpha — bidiGenerateContent (Live API) is not available on v1beta
        # for most free-tier API keys, causing 1008 errors.
        self._client          = genai.Client(
            api_key      = GEMINI_API_KEY,
            http_options = HttpOptions(api_version=LIVE_API_VER),
        )
        self._session         = None
        self._cm              = None   # the live.connect() context manager
        self._session_dead    = False  # True after a fatal error — stops all sends
        self._send_error_count = 0     # consecutive send failures (circuit breaker)

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "GeminiVoiceHandler":
        config = self._build_config()
        logger.info(f"[Gemini] Connecting with model: {LIVE_MODEL}")
        self._cm      = self._client.aio.live.connect(
            model  = LIVE_MODEL,
            config = config,
        )
        self._session = await self._cm.__aenter__()
        logger.info("[Gemini] Live session opened")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._session_dead = True
        if self._cm:
            try:
                await self._cm.__aexit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                logger.warning(f"[Gemini] Session close warning: {e}")
        logger.info("[Gemini] Live session closed")

    # ── Public interface ──────────────────────────────────────────────────────

    async def send_audio(self, pcm_16khz_bytes: bytes) -> None:
        """
        Forward patient audio (PCM 16-bit 16kHz mono) to Gemini.

        Circuit breaker:
          - Silently drops audio if session is marked dead.
          - Retries up to MAX_SEND_ERRORS times with exponential backoff.
          - Marks session dead after all retries exhausted.
        """
        if self._session is None or self._session_dead:
            return

        for attempt in range(MAX_SEND_ERRORS):
            try:
                await self._session.send_realtime_input(
                    audio=types.Blob(
                        data      = pcm_16khz_bytes,
                        mime_type = "audio/pcm;rate=16000",
                    )
                )
                # Success — reset error counter
                self._send_error_count = 0
                return

            except Exception as e:
                self._send_error_count += 1
                if attempt == 0:
                    # Only log the FIRST failure per burst to avoid spam
                    logger.error(
                        f"[Gemini] send_audio error (attempt {attempt + 1}/"
                        f"{MAX_SEND_ERRORS}): {e}"
                    )
                if attempt < MAX_SEND_ERRORS - 1:
                    # Exponential backoff before next retry
                    backoff = BASE_BACKOFF_SEC * (2 ** attempt)
                    await asyncio.sleep(backoff)
                else:
                    # All retries exhausted — kill session to stop the loop
                    logger.error(
                        "[Gemini] send_audio: max retries exhausted. "
                        "Marking session dead to stop retry loop."
                    )
                    self._session_dead = True

    async def receive(self):
        """
        Async generator — yields (kind, data) tuples from the Gemini session.

        Kinds:
          "audio"      -> bytes (PCM 24kHz 16-bit mono)  -> send to Twilio
          "transcript" -> str  (patient's speech)         -> check for emergency
          "bot_text"   -> str  (bot's own speech text)    -> for logging
        """
        if self._session is None:
            return

        try:
            async for response in self._session.receive():

                # ── Bot audio response ─────────────────────────────────────
                if response.data is not None:
                    yield ("audio", response.data)

                # ── Transcriptions via server_content ──────────────────────
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

                # Fallback: response.text (older SDK behaviour)
                elif hasattr(response, "text") and response.text:
                    yield ("bot_text", response.text)

        except Exception as e:
            # Mark session dead so send_audio stops immediately
            self._session_dead = True
            logger.error(f"[Gemini] receive error: {e}")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities          = ["AUDIO"],
            input_audio_transcription    = types.AudioTranscriptionConfig(),
            output_audio_transcription   = types.AudioTranscriptionConfig(),
            speech_config                = types.SpeechConfig(
                voice_config = types.VoiceConfig(
                    prebuilt_voice_config = types.PrebuiltVoiceConfig(
                        voice_name = "Aoede"   # warm bilingual voice
                    )
                )
            ),
            system_instruction = _SYSTEM_PROMPT,
        )
