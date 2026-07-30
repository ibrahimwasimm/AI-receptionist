"""
emergency.py — Dental emergency detection
==========================================
Two-layer detection:

  Layer 1 (keyword scan) — instant, zero API cost.
    If any emergency keyword is found in the patient's transcript,
    returns True immediately.

  Layer 2 (Gemini intent check) — only runs when Layer 1 finds nothing.
    Asks Gemini text API whether the transcript describes a dental emergency.

Usage:
    from voice.emergency import is_emergency

    # Run in a thread pool (sync function):
    result = await asyncio.to_thread(is_emergency, patient_text)
"""

import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("voice.emergency")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── Emergency keyword lists ───────────────────────────────────────────────────

_KEYWORDS_EN = {
    # Pain severity
    "severe toothache", "unbearable pain", "unbearable toothache",
    "extreme pain", "worst pain", "cannot bear",
    # Physical trauma
    "knocked out tooth", "tooth knocked out", "tooth fell out",
    "broken tooth", "cracked tooth", "fractured tooth",
    "broken jaw", "fractured jaw", "jaw injury", "jaw broken", "jaw locked",
    "cannot open mouth", "can't open mouth", "mouth won't open",
    # Bleeding
    "mouth bleeding", "heavy bleeding", "bleeding badly",
    "bleeding won't stop", "blood from mouth",
    # Infection / swelling
    "abscess", "dental abscess", "swollen face", "face swelling",
    "severe swelling", "tooth infection", "pus", "gum infection",
    # Lost work
    "lost filling", "filling fell out", "crown fell off",
    "swallowed tooth", "tooth falling out",
    # General emergency flags
    "dental emergency", "urgent dental", "emergency dentist",
    "need dentist now", "need help now",
}

_KEYWORDS_UR = {
    # Pain
    "shadeed dard", "shadeed dant dard", "bardaasht nahi",
    "bahut shadeed dard", "dard bardasht nahi ho raha",
    "itna dard", "dard bahut zyada",
    # Trauma
    "dant toot gaya", "dant toot gayi", "dant gir gaya",
    "dant nikal gaya", "dant nikal gayi",
    "jabra toot gaya", "jabra dard", "jabra band",
    "munh nahi khul raha", "munh band ho gaya",
    # Bleeding
    "munh se khoon", "khoon aa raha hai", "khoon nahi ruk raha",
    "danton se khoon",
    # Swelling / infection
    "munh sooja hua", "sojan", "sooja hua",
    "infection", "pus", "peep",
    # Lost work
    "filling nikal gayi", "filling gir gayi", "crown gir gaya",
    # General
    "dant hil raha hai", "kuch nighel liya", "emergency",
    "fauran", "abhi zaroorat", "help chahiye",
}

# Merge into one set (all lowercase for case-insensitive matching)
_ALL_KEYWORDS = {kw.lower() for kw in (_KEYWORDS_EN | _KEYWORDS_UR)}


def _keyword_check(text: str) -> bool:
    """Return True if any emergency keyword is found in the text."""
    lower = text.lower()
    return any(kw in lower for kw in _ALL_KEYWORDS)


def _openrouter_check(text: str) -> bool:
    """
    Ask an LLM via OpenRouter whether this transcript describes a dental emergency.
    Uses OPENROUTER_API_KEY from .env.
    Falls back to False on any error (including quota/rate limits).
    """
    import os, requests as req

    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.warning("[Emergency] OPENROUTER_API_KEY not set — skipping AI check")
        return False

    prompt = (
        "You are a dental emergency classifier.\n"
        "A patient called a dental clinic and said this:\n\n"
        f'"{text}"\n\n'
        "Is this a dental emergency that requires immediate dentist attention right now?\n"
        "Reply with YES or NO only. Nothing else."
    )

    try:
        resp = req.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "google/gemini-2.0-flash-exp:free",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 5,
            },
            timeout=8,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"].strip().upper()
        logger.info(f"[Emergency] OpenRouter intent check -> {answer!r}")
        return answer == "YES"

    except Exception as e:
        logger.error(f"[Emergency] OpenRouter check failed: {e}")
        return False


def is_emergency(transcript: str) -> bool:
    """
    Main entry point — call this from asyncio.to_thread().

    Returns True if the patient's speech describes a dental emergency.
    Uses instant keyword scan first; only calls Gemini if no keyword found.
    """
    if not transcript or not transcript.strip():
        return False

    # Layer 1 — fast keyword scan
    if _keyword_check(transcript):
        logger.info(f"[Emergency] ⚠️  Keyword match in: {transcript!r}")
        return True

    # Layer 2 — OpenRouter intent classification (fallback when keywords miss)
    logger.debug(f"[Emergency] No keyword found — running OpenRouter check on: {transcript!r}")
    return _openrouter_check(transcript)
