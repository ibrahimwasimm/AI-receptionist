import os
import httpx
from fastapi import Request, Response
from agent import handle_message

META_ACCESS_TOKEN    = os.getenv("META_ACCESS_TOKEN")
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID")
META_VERIFY_TOKEN    = os.getenv("META_VERIFY_TOKEN")

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
    Meta Developer Console. It passes three query params:
      hub.mode         → always "subscribe"
      hub.verify_token → must match META_VERIFY_TOKEN in your .env
      hub.challenge    → random string we must echo back to confirm
    """
    params        = dict(request.query_params)
    mode          = params.get("hub.mode")
    token         = params.get("hub.verify_token")
    challenge     = params.get("hub.challenge")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        print("[Webhook] OK Verification successful.")
        return Response(content=challenge, media_type="text/plain")

    print("[Webhook] FAILED Verification failed - token mismatch.")
    return Response(content="Forbidden", status_code=403)


# ─────────────────────────────────────────────────────────────────────────────
# Receive incoming messages  (POST)
# ─────────────────────────────────────────────────────────────────────────────

async def whatsapp_webhook(request: Request) -> Response:
    """
    Meta POSTs here every time a patient sends a WhatsApp message.
    Payload path: body → entry[0] → changes[0] → value → messages[0]
    """
    body = await request.json()
    print("--- RAW PAYLOAD ---")
    print(body)
    
    try:
        value = body["entry"][0]["changes"][0]["value"]

        # Skip delivery/read status updates — they have no "messages" key
        if "messages" not in value:
            return Response(content="ok", status_code=200)

        msg          = value["messages"][0]
        sender_phone = msg["from"]                        # e.g. "923001234567" (no +)
        text         = msg.get("text", {}).get("body", "").strip()
        
        # Extract the patient's name from their WhatsApp profile
        sender_name = "Unknown Patient"
        if "contacts" in value and len(value["contacts"]) > 0:
            sender_name = value["contacts"][0].get("profile", {}).get("name", "Unknown Patient")

        if not text:
            return Response(content="ok", status_code=200)

        safe_text = text.encode("ascii", "backslashreplace").decode("ascii")
        print(f"[WhatsApp] IN {sender_phone}: {safe_text}")

        # Send exact number (e.g. 923001234567) so Supabase lookup matches
        reply_text = handle_message(sender_phone, text, sender_name)

        await send_whatsapp_message(sender_phone, reply_text)
        safe_reply = reply_text.encode("ascii", "backslashreplace").decode("ascii")
        print(f"[WhatsApp] OUT {sender_phone}: {safe_reply}")

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
    token = os.getenv("META_ACCESS_TOKEN")   # read fresh every time
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
