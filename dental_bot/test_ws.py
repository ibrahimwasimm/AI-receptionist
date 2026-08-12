import asyncio
import websockets

async def test():
    uri = "wss://ai-receptionist-ru2r.onrender.com/media-stream"
    print(f"Testing WebSocket connection to: {uri}")
    try:
        async with websockets.connect(uri, open_timeout=15) as ws:
            print("[OK] WebSocket connected successfully! Render endpoint is reachable.")
    except Exception as e:
        print(f"[FAIL] Could not connect: {e}")

asyncio.run(test())
