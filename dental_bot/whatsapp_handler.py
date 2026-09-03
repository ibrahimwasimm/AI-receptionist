import os
import asyncio
import httpx
from fastapi import Request, Response, BackgroundTasks
from agent import handle_message

# NOTE: META_ACCESS_TOKEN is read fresh on every request so .env changes
# are picked up without restarting the server.
def _get_graph_url():
    phone_id = os.getenv("META_PHONE_NUMBER_ID")
    return f"https://graph.facebook.com/v19.0/{phone_id}/messages"


# ─────────────────────────────────────────────────────────────────────────────
# Webhook verification  (GET)
# ─────────────────────────────────────────────────────────────────────────────

async def verify_webhook(request: Request) -> Response:
    """
    Meta calls this GET endpoint once when you register the webhook in the
    Meta Developer Console.
    """
    params        = dict(request.query_params)
    mode          = params.get("hub.mode")
    token         = params.get("hub.verify_token")
    challenge     = params.get("hub.challenge")
    expected_token = os.getenv("META_VERIFY_TOKEN") or os.getenv("VERIFY_TOKEN") or "clinicdentalagent"

    if mode == "subscribe" and token == expected_token:
        print("[Webhook] OK Verification successful.")
        return Response(content=challenge, media_type="text/plain")

    print(f"[Webhook] FAILED Verification failed - token mismatch (received '{token}', expected '{expected_token}').")
    return Response(content="Forbidden", status_code=403)


PROCESSED_MESSAGE_IDS = set()


# ─────────────────────────────────────────────────────────────────────────────
# Voice Note (Audio) Transcription via Gemini
# ─────────────────────────────────────────────────────────────────────────────

async def transcribe_voice_note(audio_id: str) -> str:
    """Downloads an audio voice note from Meta and transcribes it using Google Gemini."""
    token = os.getenv("META_ACCESS_TOKEN")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Fetch media URL from Meta Graph API
            info_url = f"https://graph.facebook.com/v19.0/{audio_id}"
            resp = await client.get(info_url, headers=headers)
            if resp.status_code != 200:
                print(f"[VoiceNote] Failed to fetch media URL for {audio_id}: {resp.text}")
                return ""
            
            media_data = resp.json()
            download_url = media_data.get("url")
            raw_mime = media_data.get("mime_type", "audio/ogg")
            clean_mime = raw_mime.split(";")[0].strip()

            # 2. Download audio bytes
            audio_resp = await client.get(download_url, headers=headers)
            if audio_resp.status_code != 200:
                print(f"[VoiceNote] Failed to download audio: {audio_resp.status_code}")
                return ""
            audio_bytes = audio_resp.content

        # 3. Transcribe audio with Gemini
        from google import genai
        from google.genai import types

        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not gemini_api_key:
            print("[VoiceNote] GEMINI_API_KEY not configured.")
            return ""

        g_client = genai.Client(api_key=gemini_api_key)
        trans_resp = g_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type=clean_mime),
                "Transcribe this WhatsApp voice message from a patient verbatim. It may be in Urdu, Roman Urdu, or English. Return ONLY the transcribed text without quotes or explanations."
            ]
        )
        transcribed = trans_resp.text.strip() if trans_resp and trans_resp.text else ""
        print(f"[VoiceNote] Transcribed: '{transcribed}'")
        return transcribed

    except Exception as e:
        print(f"[VoiceNote] Transcription error: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Receive incoming messages  (POST)
# ─────────────────────────────────────────────────────────────────────────────

async def process_message_background(msg_id: str, sender_phone: str, text: str, sender_name: str):
    """Background task to handle AI processing and WhatsApp reply."""
    if msg_id in PROCESSED_MESSAGE_IDS:
        print(f"[Webhook] Duplicate message {msg_id} ignored.")
        return
    PROCESSED_MESSAGE_IDS.add(msg_id)

    if len(PROCESSED_MESSAGE_IDS) > 1000:
        PROCESSED_MESSAGE_IDS.clear()

    print(f"[WhatsApp] IN {sender_phone}: {text}")

    # Process conversation through Gemini AI logic in threadpool
    reply_text = await asyncio.to_thread(handle_message, sender_phone, text, sender_name)

    await send_whatsapp_message(sender_phone, reply_text)
    print(f"[WhatsApp] OUT {sender_phone}: {reply_text}")


async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
    """
    Meta POSTs here for incoming text, audio voice notes, or location pins.
    """
    body = await request.json()
    print("--- RAW PAYLOAD ---")
    print(body)

    try:
        value = body["entry"][0]["changes"][0]["value"]

        if "messages" not in value:
            return Response(content="ok", status_code=200)

        msg          = value["messages"][0]
        msg_id       = msg["id"]
        sender_phone = msg["from"]                        # e.g. "923001234567"
        msg_type     = msg.get("type", "text")
        text         = ""

        # Instantly deduplicate: if Meta sends duplicate webhook retries, drop them immediately
        if msg_id in PROCESSED_MESSAGE_IDS:
            print(f"[Webhook] Duplicate message ID {msg_id} dropped at webhook entrypoint.")
            return Response(content="ok", status_code=200)
        PROCESSED_MESSAGE_IDS.add(msg_id)

        if len(PROCESSED_MESSAGE_IDS) > 2000:
            PROCESSED_MESSAGE_IDS.clear()

        # Extract patient's WhatsApp name
        sender_name = "Unknown Patient"
        if "contacts" in value and len(value["contacts"]) > 0:
            sender_name = value["contacts"][0].get("profile", {}).get("name", "Unknown Patient")

        # 1. Standard Text Message
        if msg_type == "text":
            text = msg.get("text", {}).get("body", "").strip()

        # 2. WhatsApp Voice Note / Audio Message
        elif msg_type == "audio":
            audio_id = msg.get("audio", {}).get("id")
            if audio_id:
                print(f"[WhatsApp] Incoming voice note from {sender_phone} (id: {audio_id})")
                text = await transcribe_voice_note(audio_id)

        # 3. Location Pin Message
        elif msg_type == "location":
            loc = msg.get("location", {})
            loc_name = loc.get("name") or loc.get("address") or f"coordinates ({loc.get('latitude')}, {loc.get('longitude')})"
            text = f"[Patient shared location: {loc_name}. Please guide them with clinic address and directions]"

        if not text:
            return Response(content="ok", status_code=200)

        # Process in background and return 200 OK immediately
        background_tasks.add_task(process_message_background, msg_id, sender_phone, text, sender_name)

    except (KeyError, IndexError, TypeError) as e:
        print(f"[Webhook] Unexpected payload shape: {e}")

    return Response(content="ok", status_code=200)


# ─────────────────────────────────────────────────────────────────────────────
# Send a WhatsApp message via Meta Graph API
# ─────────────────────────────────────────────────────────────────────────────

async def send_whatsapp_message(to: str, text: str) -> None:
    """
    POST a text message to Meta Graph API.
    `to` — phone number WITHOUT the '+', e.g. '923001234567'
    """
    token = os.getenv("META_ACCESS_TOKEN")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "text",
        "text":              {"body": text},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(_get_graph_url(), headers=headers, json=payload)
        if resp.status_code != 200:
            print(f"[Meta API] Send error {resp.status_code}: {resp.text}")
        else:
            print(f"[Meta API] Message sent OK to {to}")

