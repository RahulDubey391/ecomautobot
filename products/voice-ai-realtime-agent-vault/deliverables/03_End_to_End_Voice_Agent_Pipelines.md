# Module 3: Full-Stack Voice Pipelines: Twilio, LiveKit, OpenAI & Deepgram

## 1. The Sub-400ms Voice Pipeline Architecture

Achieving natural, human-like voice conversations requires an end-to-end latency below 400ms. Once round-trip latency exceeds 500ms, participants begin talking over each other, causing conversational breakdown. The pipeline consists of five distinct stages, each bound to a strict latency budget.

```
[ User Speaks ] 
       │ (0-40ms Network Audio Ingress)
       ▼
[ Twilio / WebRTC Edge Gateway ] 
       │ (20ms Frame Processing)
       ▼
[ Deepgram Nova-2 Streaming STT ] ──── (120ms to Final Transcript)
       │
       ▼
[ Orchestrator / Prompt Context Engine ] ──── (10ms Serialization)
       │
       ▼
[ OpenAI GPT-4o-mini / Realtime LLM ] ──── (80-120ms Time-to-First-Token)
       │
       ▼
[ Cartesia Sonic / ElevenLabs Turbo TTS ] ──── (60-80ms Time-to-First-Byte)
       │
       ▼
[ Twilio / WebRTC Audio Egress ] ──── (40-60ms Network Egress + Jitter Buffer)
       │
[ User Hears Response ] (Total Target: 330ms - 390ms)
```

### End-to-End Latency Budget Breakdown

| Pipeline Stage | Critical Threshold | Optimization Lever | Failure Mode / Bottleneck |
| :--- | :--- | :--- | :--- |
| **1. Audio Ingress** | 40ms | Opus/PCM codec negotiation, edge termination | Twilio routing across cross-continental regions |
| **2. Streaming STT** | 120ms | Deepgram Nova-2, `endpointing=300`, `interim_results=true` | Overly aggressive VAD clipping words prematurely |
| **3. Inference (LLM)** | 100ms (TTFT) | Streamed responses, prompt tokens < 1,500, small models | Waiting for completion chunks or bloated system prompts |
| **4. Synthesis (TTS)**| 70ms (TTFB) | Cartesia Sonic, raw PCM stream over WebSockets | Chunking by complete sentences instead of punctuation clauses |
| **5. Audio Egress** | 50ms | 20ms ptime frames, local media servers, μ-law/Opus | Jitter buffer expansion on packet loss |
| **Total Target** | **380ms** | **Pipeline parallelism & early cancellation** | **Synchronous request cascades (Total > 1,200ms)** |

---

## 2. Inbound Customer Support Phone Bot

This blueprint accepts incoming telephone calls via Twilio Voice, streams raw bidirectional G.711 μ-law audio over WebSockets to an orchestration server, transcribes using Deepgram Nova-2, streams tokens through OpenAI, synthesizes audio via Cartesia Sonic, and handles barge-in interrupts instantly.

### Architecture Flow

1. Twilio receives call, requests instructions from the webhook endpoint.
2. Webhook responds with TwiML `<Connect><Stream>` to establish a full-duplex WebSocket.
3. FastAPI server reads 8000Hz μ-law audio frames from Twilio, converts them if necessary, and forwards to Deepgram.
4. When Deepgram detects speech completion, the text streams to OpenAI.
5. OpenAI text tokens stream directly to Cartesia TTS.
6. Cartesia produces 8000Hz μ-law chunks, transmitted over WebSocket to Twilio.
7. If Deepgram detects speech while the assistant is speaking, an immediate `clear` event is dispatched to Twilio, clearing its playout buffer.

### Production Implementation: `inbound_bot.py`

```python
import os
import json
import base64
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
import websockets
import httpx

app = FastAPI()

DEEPGRAM_API_KEY = os.environ["DEEPGRAM_API_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
CARTESIA_API_KEY = os.environ["CARTESIA_API_KEY"]

SYSTEM_PROMPT = """You are a high-speed customer support agent for Apex Utility Services.
Keep answers under 2 sentences. Never use lists, bullet points, or special characters.
Answer concisely and immediately help the customer resolve their account or billing issue."""

@app.post("/incoming-call")
async def incoming_call_webhook():
    xml_response = """<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Connect>
            <Stream url="wss://YOUR_DOMAIN.com/media-stream" />
        </Connect>
    </Response>"""
    return Response(content=xml_response, media_type="application/xml")

@app.websocket("/media-stream")
async def media_stream_endpoint(websocket: WebSocket):
    await websocket.accept()

    stream_sid = None
    deepgram_ws = None
    cartesia_ws = None
    llm_task = None
    tts_task = None
    is_assistant_speaking = False

    # Establish Deepgram connection (8kHz mulaw input from Twilio)
    dg_url = (
        "wss://api.deepgram.com/v1/listen?"
        "encoding=mulaw&sample_rate=8000&channels=1"
        "&model=nova-2-phonecall&endpointing=300&interim_results=true&smart_format=true"
    )
    deepgram_ws = await websockets.connect(
        dg_url, extra_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
    )

    # Establish Cartesia connection
    cartesia_url = f"wss://api.cartesia.ai/tts/websocket?api_key={CARTESIA_API_KEY}&cartesia_version=2024-06-10"
    cartesia_ws = await websockets.connect(cartesia_url)

    async def clear_twilio_buffer():
        nonlocal is_assistant_speaking
        if stream_sid and is_assistant_speaking:
            clear_msg = {"event": "clear", "streamSid": stream_sid}
            await websocket.send_text(json.dumps(clear_msg))
            is_assistant_speaking = False

    async def send_tts_to_twilio(cartesia_socket):
        nonlocal is_assistant_speaking
        try:
            async for raw_resp in cartesia_socket:
                resp = json.loads(raw_resp)
                if resp.get("data"):
                    raw_audio_b64 = resp["data"]
                    media_payload = {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": raw_audio_b64},
                    }
                    await websocket.send_text(json.dumps(media_payload))
                elif resp.get("done"):
                    is_assistant_speaking = False
        except asyncio.CancelledError:
            pass

    async def run_llm_and_tts(transcript: str):
        nonlocal is_assistant_speaking, tts_task
        is_assistant_speaking = True
        
        # Initialize Cartesia Stream Context
        context_id = f"ctx_{asyncio.get_event_loop().time()}"
        
        tts_task = asyncio.create_task(send_tts_to_twilio(cartesia_ws))

        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            }
            body = {
                "model": "gpt-4o-mini",
                "stream": True,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": transcript},
                ],
            }

            clause_buffer = ""
            async with client.stream(
                "POST", "https://api.openai.com/v1/chat/completions", headers=headers, json=body
            ) as response:
                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    
                    data = json.loads(line[6:])
                    delta = data["choices"][0]["delta"].get("content", "")
                    clause_buffer += delta

                    # Split by speech delimiters to pipeline TTS without waiting for full response
                    if any(punct in delta for punct in [".", ",", "!", "?", "\n"]):
                        cartesia_req = {
                            "context_id": context_id,
                            "model_id": "sonic-english",
                            "transcript": clause_buffer,
                            "voice": {
                                "mode": "id",
                                "id": "a0e99841-438c-4a64-b679-ae501e7d6091",  # Neutral Customer Support
                            },
                            "output_format": {
                                "container": "raw",
                                "encoding": "pcm_mulaw",
                                "sample_rate": 8000,
                            },
                            "continue": True,
                        }
                        await cartesia_ws.send(json.dumps(cartesia_req))
                        clause_buffer = ""

            # Flush remaining tokens
            if clause_buffer.strip():
                final_req = {
                    "context_id": context_id,
                    "model_id": "sonic-english",
                    "transcript": clause_buffer,
                    "voice": {
                        "mode": "id",
                        "id": "a0e99841-438c-4a64-b679-ae501e7d6091",
                    },
                    "output_format": {
                        "container": "raw",
                        "encoding": "pcm_mulaw",
                        "sample_rate": 8000,
                    },
                    "continue": False,
                }
                await cartesia_ws.send(json.dumps(final_req))

    async def handle_deepgram_transcripts():
        nonlocal llm_task
        try:
            async for raw_message in deepgram_ws:
                message = json.loads(raw_message)
                if not message.get("is_final"):
                    # Check for barge-in: If user speaks interim words while assistant is active
                    if message.get("channel", {}).get("alternatives", [{}])[0].get("transcript", ""):
                        if is_assistant_speaking:
                            await clear_twilio_buffer()
                            if llm_task and not llm_task.done():
                                llm_task.cancel()
                            if tts_task and not tts_task.done():
                                tts_task.cancel()
                    continue

                transcript = message["channel"]["alternatives"][0]["transcript"].strip()
                if transcript:
                    if llm_task and not llm_task.done():
                        llm_task.cancel()
                    if tts_task and not tts_task.done():
                        tts_task.cancel()
                    await clear_twilio_buffer()
                    llm_task = asyncio.create_task(run_llm_and_tts(transcript))
        except asyncio.CancelledError:
            pass

    dg_task = asyncio.create_task(handle_deepgram_transcripts())

    try:
        while True:
            raw_msg = await websocket.receive_text()
            data = json.loads(raw_msg)
            event_type = data.get("event")

            if event_type == "start":
                stream_sid = data["start"]["streamSid"]
            elif event_type == "media":
                payload = data["media"]["payload"]
                audio_bytes = base64.b64decode(payload)
                await deepgram_ws.send(audio_bytes)
            elif event_type == "stop":
                break
    except WebSocketDisconnect:
        pass
    finally:
        for task in [dg_task, llm_task, tts_task]:
            if task and not task.done():
                task.cancel()
        await deepgram_ws.close()
        await cartesia_ws.close()
```

---

## 3. Outbound Appointment Scheduler

The outbound appointment scheduler utilizes the LiveKit Agents framework combined with Twilio SIP Trunking to initiate calls and interact with a booking calendar API via structured Tool Calling.

```
┌────────────────┐      SIP Trunk       ┌──────────────────┐
│  Twilio Voice  │ ◄──────────────────► │  LiveKit Server  │
└────────────────┘                      └─────────┬────────┘
                                                  │ WebRTC Audio
                                                  ▼
                                        ┌──────────────────┐
                                        │  Agent Worker    │
                                        │ (livekit-agents) │
                                        └─────────┬────────┘
                                                  │ Function Calls
                                                  ▼
                                        ┌──────────────────┐
                                        │   Cal.com API    │
                                        └──────────────────┘
```

### Production Implementation: `outbound_agent.py`

```python
import os
import json
import httpx
from datetime import datetime, timezone
from livekit import agents
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import deepgram, openai, cartesia, silero

CALCOM_API_KEY = os.environ["CALCOM_API_KEY"]
CALCOM_EVENT_TYPE_ID = int(os.environ["CALCOM_EVENT_TYPE_ID"])

def fetch_available_slots(start_date: str, end_date: str) -> str:
    """Fetch open calendar booking slots from Cal.com between two ISO 8601 timestamps."""
    url = "https://api.cal.com/v1/slots"
    params = {
        "apiKey": CALCOM_API_KEY,
        "eventTypeId": CALCOM_EVENT_TYPE_ID,
        "startTime": start_date,
        "endTime": end_date,
    }
    with httpx.Client() as client:
        res = client.get(url, params=params)
        if res.status_code != 200:
            return json.dumps({"error": f"Failed fetching slots: {res.text}"})
        slots = res.json().get("slots", {})
        return json.dumps({"available_slots": slots})

def book_appointment_slot(name: str, email: str, start_time_iso: str) -> str:
    """Book an appointment on Cal.com given name, email, and confirmed start time."""
    url = f"https://api.cal.com/v1/bookings?apiKey={CALCOM_API_KEY}"
    payload = {
        "eventTypeId": CALCOM_EVENT_TYPE_ID,
        "start": start_time_iso,
        "name": name,
        "email": email,
        "timeZone": "America/New_York",
        "language": "en",
        "metadata": {"source": "ai_voice_scheduler"},
    }
    with httpx.Client() as client:
        res = client.post(url, json=payload)
        if res.status_code in [200, 201]:
            booking_data = res.json().get("booking", {})
            return json.dumps({
                "status": "confirmed",
                "id": booking_data.get("id"),
                "startTime": booking_data.get("startTime"),
            })
        return json.dumps({"status": "failed", "detail": res.text})

async def entrypoint(ctx: JobContext):
    await ctx.connect()

    # Define function schemas for LLM tool invocation
    tools = [
        {
            "type": "function",
            "function": {
                "name": "fetch_available_slots",
                "description": "Get available booking slots between two UTC ISO 8601 dates.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string", "description": "ISO 8601 start date-time (e.g. 2025-04-01T00:00:00Z)"},
                        "end_date": {"type": "string", "description": "ISO 8601 end date-time (e.g. 2025-04-02T23:59:59Z)"},
                    },
                    "required": ["start_date", "end_date"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "book_appointment_slot",
                "description": "Finalize an appointment booking once the client explicitly confirms the slot.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Full legal name of the user"},
                        "email": {"type": "string", "description": "Email address for calendar invitation"},
                        "start_time_iso": {"type": "string", "description": "ISO 8601 formatted start time for booking"},
                    },
                    "required": ["name", "email", "start_time_iso"],
                },
            },
        },
    ]

    agent = VoicePipelineAgent(
        vad=silero.VAD.load(min_speech_duration=0.1, min_silence_duration=0.3),
        stt=deepgram.STT(model="nova-2-general", language="en"),
        llm=openai.LLM(
            model="gpt-4o-mini",
            temperature=0.2,
        ),
        tts=cartesia.TTS(
            model="sonic-english",
            voice="79a125e8-cd45-4c13-8a67-188112f4dd22", # Professional Sales Persona
        ),
        chat_ctx=openai.ChatContext(
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Current Date: {datetime.now(timezone.utc).isoformat()}. "
                        "You are Sarah, an outbound booking assistant for Precision Dental. "
                        "Your goal is to reschedule the user's missed dental examination. "
                        "Be concise, natural, and never invent availability. Always invoke fetch_available_slots. "
                        "Once a time is selected, repeat it back and verify their email before booking."
                    ),
                }
            ]
        ),
    )

    # Attach tool executors
    @agent.llm.on("tool_call")
    def on_tool_call(tool_call, callback):
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if name == "fetch_available_slots":
            res = fetch_available_slots(args["start_date"], args["end_date"])
            callback(res)
        elif name == "book_appointment_slot":
            res = book_appointment_slot(args["name"], args["email"], args["start_time_iso"])
            callback(res)

    agent.start(ctx.room)
    await agent.say("Hello, this is Sarah from Precision Dental calling to follow up on your six-month exam. Do you have a quick moment to look at scheduling an appointment?", allow_interruptions=True)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
```

### Dispatching Outbound Calls to Twilio via LiveKit SIP API: `dispatch_caller.py`

```python
import os
import asyncio
from livekit import api

async def make_outbound_call(destination_number: str):
    livekit_url = os.environ["LIVEKIT_URL"]
    api_key = os.environ["LIVEKIT_API_KEY"]
    api_secret = os.environ["LIVEKIT_API_SECRET"]
    sip_trunk_id = os.environ["LIVEKIT_SIP_TRUNK_ID"]

    lkapi = api.LiveKitAPI(livekit_url, api_key, api_secret)

    room_name = f"outbound-{int(asyncio.get_event_loop().time())}"

    # 1. Create Room explicitly
    await lkapi.room.create_room(api.CreateRoomRequest(name=room_name))

    # 2. Trigger SIP Outbound Participant
    sip_request = api.CreateSIPParticipantRequest(
        sip_trunk_id=sip_trunk_id,
        sip_call_to=destination_number,
        room_name=room_name,
        participant_identity=f"phone_{destination_number}",
        participant_name="Outbound Lead",
    )

    participant = await lkapi.sip.create_sip_participant(sip_request)
    print(f"SIP Call dispatched: ID {participant.participant_id} to {destination_number}")
    await lkapi.aclose()

if __name__ == "__main__":
    asyncio.run(make_outbound_call("+14155552671"))
```

---

## 4. Multilingual Live Translation Stream

The multilingual translation bridge allows two participants speaking different languages (e.g., Spanish and English) to converse in real time. It transcribes the source language, translates the stream, and synthesizes the translation in the target language while maintaining a voice signature.

```
[ User A (Spanish) ] 
       │
       ▼  Audio Stream 1 (es)
[ Deepgram Nova-2 (es) ]
       │
       ▼  Interim & Final Transcripts
[ GPT-4o-mini Streaming Translation Matrix ]
       │
       ▼  English Stream
[ Cartesia Sonic (Voice Clone: User A) ] 
       │
       ▼  Synthesized Voice (en)
[ User B (English) ]
```

### Production Implementation: `translation_bridge.py`

```python
import os
import json
import asyncio
import websockets
from livekit import agents
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import cartesia, deepgram, openai, silero

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
CARTESIA_API_KEY = os.environ["CARTESIA_API_KEY"]

TRANSLATION_SYSTEM_PROMPT = """You are an instantaneous voice-to-voice machine translator.
Translate Spanish speech into conversational, idiomatic English.
Rules:
1. Output ONLY the English translation.
2. Never explain, apologize, or add commentary.
3. Preserve emotional tone, hesitation markers, and conversational register.
4. Translate idioms to natural equivalents rather than literal translations."""

class DynamicTranslationStream:
    def __init__(self, target_sink, cartesia_voice_id: str):
        self.target_sink = target_sink
        self.voice_id = cartesia_voice_id
        self.cartesia_ws = None
        self.context_id = "translation_ctx"

    async def initialize(self):
        url = f"wss://api.cartesia.ai/tts/websocket?api_key={CARTESIA_API_KEY}&cartesia_version=2024-06-10"
        self.cartesia_ws = await websockets.connect(url)
        asyncio.create_task(self._process_tts_returns())

    async def _process_tts_returns(self):
        try:
            async for raw in self.cartesia_ws:
                data = json.loads(raw)
                if data.get("data"):
                    pcm_bytes = data["data"]
                    # Forward PCM directly to target room audio track
                    await self.target_sink.write_frame(pcm_bytes)
        except websockets.exceptions.ConnectionClosed:
            pass

    async def translate_and_synthesize(self, spanish_text: str):
        # OpenAI Streaming Translation
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "gpt-4o-mini",
            "temperature": 0.0,
            "stream": True,
            "messages": [
                {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                {"role": "user", "content": spanish_text},
            ],
        }

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", "https://api.openai.com/v1/chat/completions", headers=headers, json=body) as resp:
                buffer = ""
                async for line in resp.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    payload = json.loads(line[6:])
                    delta = payload["choices"][0]["delta"].get("content", "")
                    buffer += delta

                    if any(c in delta for c in [",", ".", "?", "!"]):
                        req = {
                            "context_id": self.context_id,
                            "model_id": "sonic-multilingual",
                            "transcript": buffer,
                            "voice": {"mode": "id", "id": self.voice_id},
                            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000},
                            "continue": True,
                        }
                        await self.cartesia_ws.send(json.dumps(req))
                        buffer = ""

                if buffer.strip():
                    req = {
                        "context_id": self.context_id,
                        "model_id": "sonic-multilingual",
                        "transcript": buffer,
                        "voice": {"mode": "id", "id": self.voice_id},
                        "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000},
                        "continue": False,
                    }
                    await self.cartesia_ws.send(json.dumps(req))

async def entrypoint(ctx: JobContext):
    await ctx.connect()

    # User A: Spanish Inbound Channel
    # User B: English Inbound Channel
    stt_spanish = deepgram.STT(model="nova-2-general", language="es")
    
    # Dynamic listener to identify remote participants
    @ctx.room.on("participant_connected")
    def on_participant(participant):
        print(f"Translator connected to: {participant.identity}")

    # Set up pipeline agent for the Spanish -> English leg
    agent = VoicePipelineAgent(
        vad=silero.VAD.load(),
        stt=stt_spanish,
        llm=openai.LLM(model="gpt-4o-mini", temperature=0.0),
        tts=cartesia.TTS(model="sonic-multilingual", voice="248be419-c632-4f23-afd1-0799497a9f35"),
        chat_ctx=openai.ChatContext(
            messages=[{"role": "system", "content": TRANSLATION_SYSTEM_PROMPT}]
        ),
    )
    agent.start(ctx.room)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
```

---

## 5. Browser-Based WebRTC Voice Copilot

WebRTC enables browser clients to bypass standard HTTP streaming overhead, executing full-duplex conversations with client-side UI telemetry and sub-300ms execution.

```
 Browser Client (Microphone)
       │
       ▼ Opus Audio over WebRTC Data/Media Tracks
 LiveKit Cloud / Edge Mesh
       │
       ▼ Local WebRTC Peer Connection
 Voice Agent (Server Worker)
       │
       ▼ Client Tools & Real-time Visualizer Hooks
 WebRTC Data Channel Event (e.g. Canvas Drawing / Route Change)
```

### Server Token Generation: `server.js` (Node/Express)

```javascript
import express from 'express';
import { AccessToken } from 'livekit-server-sdk';
import dotenv from 'dotenv';
dotenv.config();

const app = express();
app.use(express.json());

app.post('/api/get-join-token', async (req, res) => {
  const { roomName, identity } = req.body;

  if (!roomName || !identity) {
    return res.status(400).json({ error: 'roomName and identity required' });
  }

  const at = new AccessToken(
    process.env.LIVEKIT_API_
