import asyncio
import logging
import os
from dotenv import load_dotenv

from livekit.agents import AutoSubscribe, JobContext, JobProcess, WorkerOptions, cli, voice
from livekit.plugins import openai, deepgram, elevenlabs, silero

# Load environment variables
load_dotenv(override=True)

logger = logging.getLogger("voice-agent")

# Reuse clinic name
CLINIC_NAME = os.getenv("CLINIC_NAME", "Smile Dental Clinic")

def prewarm(proc: JobProcess):
    """Prewarm local Silero VAD model."""
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    """Entrypoint for LiveKit Voice Agent (SDK v1.x)."""
    logger.info(f"Connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # 1. Wait for caller
    participant = await ctx.wait_for_participant()
    logger.info(f"Started voice session with participant: {participant.identity}")

    # 2. Define the Agent with system instructions
    agent = voice.Agent(
        instructions=(
            f"You are Sana, a warm and professional dental receptionist at {CLINIC_NAME}. "
            "You are speaking to a patient on the phone. "
            "Your responses MUST be short, conversational, and natural. Do not use markdown or lists. "
            "If they speak Urdu, reply in Roman Urdu. If English, reply in English. "
            "Ask how you can help them today. Wait for them to respond before continuing."
        ),
    )

    # 3. Create the AgentSession
    session = voice.AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(),
        llm=openai.LLM(
            model="openrouter/free", 
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY")
        ),
        tts=elevenlabs.TTS(
            model="eleven_turbo_v2_5",
            api_key=os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVEN_API_KEY"),
            voice_id="CwhRBWXzGAHq8TQ4Fs17"
        ),
    )

    # 4. Start the agent session in the room
    await session.start(agent, room=ctx.room)

    # 5. Greet the patient
    session.say("Hello, this is Sana from Smile Dental Clinic. How can I help you today?", allow_interruptions=True)

if __name__ == "__main__":
    # Run with: python voice_agent.py dev
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )
