# Module 1: Voice AI System Architecture & Latency Engineering

To achieve human-parity conversational voice AI, your system must operate with an end-to-end acoustic-to-acoustic latency below **400 milliseconds**. Human conversation exhibits a natural turn-taking gap between 200ms and 300ms. Once latency exceeds 500ms, users begin talking over the agent, causing collision loops, broken turn-taking states, and rapid conversational breakdown.

This module details the low-latency network layers, packet serialization formats, Voice Activity Detection (VAD) mechanics, and jitter buffering strategies required to sustain conversational real-time voice infrastructure at scale.

---

## 1. Transport Protocols Compared: WebRTC vs. WebSockets vs. SIP/RTP

Every conversational pipeline begins with audio transport across the public internet. Choosing the wrong protocol at the ingress boundary introduces unavoidable latency penalties before your inference models process a single byte.

```
+---------------------------------------------------------------------------------------------------+
|                                  PROTOCOL STACK & TOPOLOGY COMPARISON                             |
+---------------------------------------------------------------------------------------------------+
| 1. WebRTC Data/Media Path (Browser / Native Mobile)                                              |
|    Client (Microphone) ---> SRTP (UDP) via ICE/STUN/TURN ---> Media Gateway / SFU ---> Worker     |
|    * Latency: 15-40ms | Transport: UDP | Framing: 20ms Opus | Handshake: DTLS-SRTP (3-way)        |
+---------------------------------------------------------------------------------------------------+
| 2. Telephony SIP Trunking (Twilio / Telnyx / Carrier Ingress)                                     |
|    Telco Carrier ---> SIP INVITE (UDP/TLS) ---> RTP / G.711u (UDP) ---> Media Server / AudioHook    |
|    * Latency: 20-60ms | Transport: UDP | Framing: 20ms u-law | Handshake: SIP / SDP exchange     |
+---------------------------------------------------------------------------------------------------+
| 3. Telephony Media Streams (Twilio / Telnyx WebSocket Bridges)                                    |
|    Telco Carrier ---> Carrier Media Gateway ---> JSON Base64/Binary over TLS (TCP) ---> App Server|
|    * Latency: 60-150ms | Transport: TCP | Framing: 20ms chunk | Handshake: TCP + TLS + HTTP WS    |
+---------------------------------------------------------------------------------------------------+
```

### Architectural Trade-Off Matrix

| Engineering Metric | WebRTC (Audio Stream) | WebSockets (Binary / Base64) | SIP / Direct RTP Trunking |
| :--- | :--- | :--- | :--- |
| **Transport Layer** | UDP (via ICE / DTLS / SRTP) | TCP (TLS Encrypted) | UDP (Plain RTP or SRTP) |
| **Ingress Latency** | **10ms – 40ms** | **50ms – 180ms** | **15ms – 50ms** |
| **Head-of-Line Blocking** | **None** (Dropped packets dropped) | **Guaranteed** (TCP retries stall stream) | **None** (Out-of-order drop policy) |
| **Packet Overhead** | Minimal (RTP header: 12 bytes) | High (TCP 20-60B + TLS 29B + WS 2-10B + Base64 33%) | Lowest (IP + UDP + RTP = 40 bytes) |
| **NAT Traversal** | Built-in via ICE / STUN / TURN | Standard outbound 443/TCP egress | Requires SBC (Session Border Controller) |
| **Native Codecs** | Opus (48kHz, dynamic bitrate) | Any (commonly 8kHz G.711 or 16k PCM) | G.711u, G.711a, G.729, Opus (rare) |
| **Production Target** | Web, iOS, Android, custom hardware | Twilio/Telnyx bridge backends | Direct carrier interconnects (Kamailio, FreeSWITCH) |

### Engineering Verdict & Topology Selection

1. **Browser / Mobile Native Agents:** Standardize on **WebRTC**. WebSockets over TCP incur head-of-line blocking under packet loss. If a packet drops on a cellular connection, TCP halts all subsequent packets until retransmission completes, producing an audible audio stutter of 200ms–800ms. WebRTC uses UDP; dropped frames are simply interpolated via Opus Packet Loss Concealment (PLC).
2. **Telephony via CPaaS (Twilio, Telnyx, Vonage):** Use **Raw Binary WebSockets** or **Direct SIP Ingress**. If using Twilio Media Streams, bypass JSON-Base64 encoding by using custom bidirectional Media Streams with raw binary payloads where supported, or terminate SIP directly into an open-source media gateway (LiveKit SIP, FreeSWITCH, or Asterisk) to strip the carrier RTP and convert it directly to an internal WebRTC/UDP track.

---

## 2. Audio Packet Streaming, Codecs, and Framing

Voice pipelines must process audio as continuous 20ms chunks. Audio hardware operates on sample frames. Sending chunks larger than 20ms introduces pipeline latency; sending chunks smaller than 10ms increases network overhead due to IP/UDP/RTP packet headers.

### Audio Math Reference Table

| Codec | Sample Rate | Bit Depth | Channels | Frame Duration | Samples per Frame | Raw Payload Size |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **PCM16 (Linear)** | 8,000 Hz | 16-bit (2 B) | 1 (Mono) | 20 ms | 160 | 320 Bytes |
| **PCM16 (Linear)** | 16,000 Hz | 16-bit (2 B) | 1 (Mono) | 20 ms | 320 | 640 Bytes |
| **PCM16 (Linear)** | 24,000 Hz | 16-bit (2 B) | 1 (Mono) | 20 ms | 480 | 960 Bytes |
| **G.711 μ-law (PCMU)**| 8,000 Hz | 8-bit (1 B) | 1 (Mono) | 20 ms | 160 | 160 Bytes |
| **Opus (Voice Profile)**| 48,000 Hz | Compressed | 1 (Mono) | 20 ms | 960 | Variable (40–80 Bytes) |

### Frame Size Calculation Formula

$$\text{Bytes per Frame} = \text{Sample Rate (Hz)} \times \left(\frac{\text{Bit Depth}}{8}\right) \times \text{Channels} \times \left(\frac{\text{Frame Duration (ms)}}{1000}\right)$$

*Example for 16kHz, 16-bit Mono Linear PCM at 20ms:*
$$16000 \times 2 \times 1 \times 0.020 = 640 \text{ Bytes}$$

### Production Opus Configuration Profile

When using WebRTC or native Opus encoding, pass the following parameters to the Opus encoder to optimize strictly for voice-over-IP:

```ini
application=voip
maxaveragebitrate=24000
cbr=true
usedtx=false
useinbandfec=true
complexity=4
maxplaybackrate=16000
frame_size=20
```

* **`application=voip`**: Bias codec toward the SILK human speech model rather than the CELT musical model.
* **`cbr=true` (Constant Bitrate)**: Eliminates bit-budget fluctuation and prevents jitter spikes across constrained network hops.
* **`useinbandfec=true` (Forward Error Correction)**: Embeds lower-resolution redundant data from the preceding frame into the current frame. Under up to 20% random packet loss, the decoder reconstructs missing speech without requesting packet retransmission.
* **`usedtx=false` (Discontinuous Transmission)**: Disable DTX. While DTX saves bandwidth during silence, it introduces a 20–40ms activation penalty when speech resumes, frequently cutting off the initial consonant of the first word.

---

## 3. The Sub-400ms End-to-End Latency Budget

To orchestrate real-time interactions, you must measure acoustic-to-acoustic latency: the time elapsed from the exact moment the speaker's vocal cords stop moving until the speaker's ear receives the first acoustic wave of the agent's response.

```
+---------------------------------------------------------------------------------------------------+
|                        SUB-400ms LATENCY BUDGET (CASCADED STT-LLM-TTS PIPELINE)                   |
+---------------------------------------------------------------------------------------------------+
| [0ms]    Speaker Stops Talking                                                                    |
|  |--- 20ms   : Client Audio Hardware Ingress Framing (20ms buffer)                                |
|  |--- 25ms   : Network Ingress (WebRTC SRTP Transport to Cloud Edge)                             |
|  |--- 80ms   : Voice Activity Detection (VAD) Speech End Detection (Minimum Silence Window)       |
| [125ms]  Turn-End Finalized -> Dispatch Audio Buffer to STT Engine                               |
|  |--- 75ms   : Streaming STT Final Transcript Emission (Deepgram Nova-2 / FastConformer)          |
| [200ms]  Text Emitted -> Stream First Token Request to LLM                                        |
|  |--- 90ms   : LLM Time-To-First-Token (TTFT) (Groq Llama-3-70B / Cerebras / vLLM Stream)        |
| [290ms]  First 3 Token Sentence Boundary Reached -> Dispatch Text to TTS Engine                   |
|  |--- 55ms   : TTS Time-to-First-Audio-Chunk (Cartesia Sonic / ElevenLabs Turbo v2.5)             |
| [345ms]  First Audio Chunk Generated (200ms Audio Slice) -> Network Egress Buffer                 |
|  |--- 25ms   : Network Egress (SRTP back to Client Device)                                        |
|  |--- 20ms   : Client Audio Hardware Egress Jitter Buffer Playout                                 |
| [390ms]  Sound Waves Emit from Speaker's Earpiece                                                 |
+---------------------------------------------------------------------------------------------------+
| TOTAL ACCUMULATED LATENCY: 390 MILLISECONDS                                                       |
+---------------------------------------------------------------------------------------------------+
```

### Cascade vs. Direct Speech-to-Speech (S2S) Architecture

```
+---------------------------------------------------------------------------------------------------+
| CONFIGURATION A: Cascaded Pipeline (STT -> LLM -> TTS)                                           |
| Audio In -> [STT] -> Text Tokens -> [LLM] -> Text Tokens -> [TTS] -> Audio Out                    |
| Pros: Deterministic guardrails, tool calls, complete provider modularity, low token pricing.      |
| Target Budget: 350ms - 420ms                                                                      |
+---------------------------------------------------------------------------------------------------+
| CONFIGURATION B: Native Multi-Modal / Speech-to-Speech (e.g., OpenAI Realtime / Gemini Live)       |
| Audio In -------------------------> [Native Multi-Modal S2S] -------------------------> Audio Out |
| Pros: Retains emotion, paralinguistic tone, lower architectural hops.                             |
| Cons: High cost, complex prompt injection guardrails, vendor lock-in.                             |
| Target Budget: 280ms - 380ms                                                                      |
+---------------------------------------------------------------------------------------------------+
```

### Detailed Component Budget Constraints

```
+-----------------------------------+-------------------+--------------------+
| Pipeline Stage                    | Target Execution  | Maximum Timeout    |
+-----------------------------------+-------------------+--------------------+
| 1. Ingress Network + Framing      | 45 ms             | 65 ms              |
| 2. Silero VAD Turn-End Commit     | 80 ms             | 120 ms             |
| 3. Streaming STT Finalization     | 75 ms             | 110 ms             |
| 4. LLM Time to First Token (TTFT) | 90 ms             | 140 ms             |
| 5. TTS Time to First Chunk (TTFB) | 55 ms             | 90 ms              |
| 6. Egress Network + Jitter Buffer | 45 ms             | 65 ms              |
+-----------------------------------+-------------------+--------------------+
| TOTAL SYSTEM LATENCY              | 390 ms            | 590 ms (Degraded)  |
+-----------------------------------+-------------------+--------------------+
```

---

## 4. Voice Activity Detection (VAD) & Barge-In Mechanics

The critical failure point in voice agents is inaccurate Voice Activity Detection (VAD). If the agent takes 400ms of silence to determine that the user has stopped speaking, you have consumed the entire latency budget on silence detection alone.

### Turning-Point Parameters (Silero VAD)

* **Speech Threshold (`0.45 - 0.55`)**: Probability threshold above which an audio frame is classified as voice. Setting this too low causes background noise or breathing to register as active speech.
* **Minimum Speech Duration (`60ms - 100ms`)**: Audio spikes below this length (coughs, mic pops, clicks) are discarded.
* **Negative Speech Silence Duration (`80ms - 120ms`)**: The duration of uninterrupted silence required before the VAD officially triggers a `TURN_COMPLETE` event. Telephony typically requires 150ms–200ms due to line echo; WebRTC environments with acoustic echo cancellation (AEC) can safely operate at 80ms–100ms.
* **Pre-Speech Buffer (`120ms`)**: A circular audio buffer that prepends audio immediately preceding the trigger point to prevent clipping the first syllable.

```
       User Speaking               Silence Window           Agent Pipeline Dispatched
[ Audio Energy Detected ] ---> [ 80ms No Voice Energy ] ---> [ EMIT: TURN_COMPLETE ]
                                       |
                   If speech resumes at 60ms:
                   [ Reset Silence Timer ] ---> Continue Ingress (No Interruption)
```

### Barge-In & Interruption State Machine

When an agent is actively streaming synthesized speech to the user, the ingress stream must monitor for user voice input. The moment user speech is confirmed, the system must trigger an immediate cancellation cascade:

```
[Agent Speaking: Audio Streaming Outbound]
                     │
                     ▼
      User Begins Speaking: "Wait, stop..."
                     │
                     ▼
[Ingress VAD: Speech Confirmed (>60ms, P>0.5)]
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
1. Abort Controller:    2. Drain Network:        3. Clear Buffers:
   - Cancel LLM Stream     - Send RTP Clear Packet  - Purge Client Playout
   - Halt TTS Generation   - Flush Socket Queue     - Reset STT Tracking
```

---

## 5. Production Implementation: Real-Time Audio Chunker, VAD & Jitter Buffer

The following production-ready Python service uses `asyncio`, circular memory buffers, and the Silero VAD ONNX runtime to manage full-duplex, low-latency audio chunking, turn-end detection, and instantaneous interruption (barge-in) dispatch.

```python
#!/usr/bin/env python3
"""
High-Performance Real-Time Audio Engine
Handles: 20ms Frame Ingress, Streaming Silero VAD, Barge-in Interruptions, Jitter Buffering.
Requirements: numpy, onnxruntime
"""

import asyncio
import collections
import time
from typing import AsyncGenerator, Callable, Deque, Optional
import numpy as np
import onnxruntime as ort


class SileroVADDetector:
    """Ultra-low latency streaming VAD using Silero VAD v4 via ONNX Runtime."""

    def __init__(self, model_path: str, sample_rate: int = 16000, threshold: float = 0.5):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.window_size_samples = 512 if sample_rate == 16000 else 256  # 32ms window
        
        # Configure ONNX runtime for ultra-low inference latency
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        
        self.session = ort.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])
        self.reset_states()

    def reset_states(self):
        """Reset internal recurrent neural network states."""
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def process_frame(self, frame_pcm16: bytes) -> float:
        """
        Process a single audio frame (512 samples / 32ms for 16kHz).
        Returns the speech probability [0.0 - 1.0].
        """
        audio_data = np.frombuffer(frame_pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Ensure input frame matches expected window size exactly
        if len(audio_data) != self.window_size_samples:
            if len(audio_data) < self.window_size_samples:
                audio_data = np.pad(audio_data, (0, self.window_size_samples - len(audio_data)))
            else:
                audio_data = audio_data[:self.window_size_samples]

        audio_tensor = np.expand_dims(audio_data, axis=0)  # Shape: [1, 512]
        sr_tensor = np.array(self.sample_rate, dtype=np.int64)

        ort_inputs = {
            "input": audio_tensor,
            "h": self._h,
            "c": self._c,
            "sr": sr_tensor
        }
        
        out, self._h, self._c = self.session.run(None, ort_inputs)
        return float(out[0][0])


class AdaptiveJitterBuffer:
    """
    Fixed-Allocation Adaptive Playback Jitter Buffer.
    Compensates for network latency variance without introducing unbounded delay.
    """

    def __init__(self, target_delay_ms: int = 40, frame_duration_ms: int = 20):
        self.target_frames = target_delay_ms // frame_duration_ms
        self.frame_duration_ms = frame_duration_ms
        self.buffer: Deque[bytes] = collections.deque()
        self.is_buffering = True

    def push(self, packet: bytes):
        """Push an incoming audio frame into the jitter buffer."""
        self.buffer.append(packet)
        if self.is_buffering and len(self.buffer) >= self.target_frames:
            self.is_buffering = False

    def pop(self) -> Optional[bytes]:
        """Fetch the next playable audio frame. Returns silence frame if dry."""
        if self.is_buffering:
            return None
        
        if len(self.buffer) > 0:
            return self.buffer.popleft()
        
        # Buffer under-run: trigger immediate rebuffering
        self.is_buffering = True
        return None

    def flush(self):
        """Immediately clear the buffer (used for barge-in interruptions)."""
        self.buffer.clear()
        self.is_buffering = True


class RealtimeVoiceDuplexCoordinator:
    """
    Coordinates duplex audio streaming, VAD turn-taking, and barge-in execution.
    Targeted for 16kHz Mono 16-bit PCM streams.
    """

    def __init__(
        self,
        vad_model_path: str,
        on_turn_complete: Callable[[bytes], asyncio.Task],
        on_barge_in: Callable[[], None],
    ):
        self.vad = SileroVADDetector(model_path=vad_model_path, sample_rate=16000)
        self.on_turn_complete = on_turn_complete
        self.on_barge_in = on_barge_in

        # Audio Constants
        self.bytes_per_sample = 2
        self.sample_rate = 16000
        # 32ms frame = 512 samples = 1024 bytes (Matches Silero optimal input)
        self.chunk_size_bytes = 1024
        
        # Pipeline Timing Hyperparameters
        self.min_speech_duration_ms = 64
        self.min_silence_duration_ms = 100
        
        # Internal State Management
        self.is_agent_speaking = False
        self.user_is_speaking = False
        self.speech_start_time = 0.0
        self.silence_start_time = 0.0
        
        # Ring buffers for history and turn recording
        self.pre_roll_buffer = collections.deque(maxlen=4)  # ~128ms pre-roll
        self.active_turn_buffer = bytearray()
        
    def set_agent_speaking_state(self, speaking: bool):
        """Track whether downstream agent is actively outputting audio."""
        self.is_agent_speaking = speaking

    async def ingest_audio_stream(self, stream_generator: AsyncGenerator[bytes, None]):
        """
        Main processing loop. Consumes raw chunked audio, runs VAD, 
        and controls conversational flow.
        """
        accumulator = bytearray()

        async for raw_bytes in stream_generator:
            accumulator.extend(raw_bytes)

            while len(accumulator) >= self.chunk_size_bytes:
                frame = bytes(accumulator[:self.chunk_size_bytes])
                del accumulator[:self.chunk_size_bytes]

                now = time.monotonic()
                speech_prob = self.vad.process_frame(frame)
                is_voice = speech_prob >= self.vad.threshold

                if is_voice:
                    # 1. Check for Barge-in Condition
                    if self.is_agent_speaking and not self.user_is_speaking:
                        if self.speech_start_time == 0.0:
                            self.speech_start_time = now
                        elif (now - self.speech_start_time) * 1000 >= self.min_speech_duration_ms:
                            # Confirmed user speech during agent output: interrupt immediately
                            self.on_barge_in()
                            self.is_agent_speaking = False
                            self.user_is_speaking = True
                            self.active_turn_buffer.extend(b"".join(self.pre_roll_buffer))

                    # 2. Track Standard User Speech Start
                    elif not self.user_is_speaking:
                        if self.speech_start_time == 0.0:
                            self.speech_start_time = now
                        elif (now - self.speech_start_time) * 1000 >= self.min_speech_duration_ms:
                            self.user_is_speaking = True
                            # Prepend pre-roll buffer to prevent clipped consonants
                            self.active_turn_buffer.extend(b"".join(self.pre_roll_buffer))

                    if self.user_is_speaking:
                        self.active_turn_buffer.extend(frame)
                        self.silence_start_time = 0.0

                    self.pre_roll_buffer.append(frame)

                else:
                    # Speech energy is absent
                    self.speech_start_time = 0.0

                    if self.user_is_speaking:
                        self.active_turn_buffer.extend(frame)
                        if self.silence_start_time == 0.0:
                            self.silence_start_time = now
                        elif (now - self.silence_start_time) * 1000 >= self.min_silence_duration_ms:
                            # 3. Finalize Turn and Dispatch to Pipeline
                            self.user_is_speaking = False
                            turn_audio = bytes(self.active_turn_buffer)
                            self.active_turn_buffer.clear()
                            self.silence_start_time = 0.0
                            self.vad.reset_states()
                            
                            # Fire turn payload asynchronously without stalling ingress loop
                            asyncio.create_task(self._dispatch_turn(turn_audio))
                    else:
                        self.pre_roll_buffer.append(frame)

    async def _dispatch_turn(self, audio_payload: bytes):
        """Dispatches committed user speech turn to STT/LLM pipeline."""
        if len(audio_payload) > 0:
            await self.on_turn_complete(audio_payload)
```

---

## 6. Jitter Buffer Strategies for Voice Agents

Telephony networks and mobile connections introduce packet arrival variations known as **network jitter**. Without proper buffering, variations in packet arrival times result in audible buffer under-runs (clicks, pops, dropped syllables).

```
Network Ingress (Variable Arrival Times)
[Packet 1] --- 20ms ---> [Packet 2] ------ 80ms (JITTER SPIKE) ------> [Packet 3]
                              │
                              ▼
        Adaptive Jitter Buffer (Target: 40ms Target Window)
        [ Packet 1 (Hold) ][ Packet 2 (Play) ][ Interpolate/PLC ][ Packet 3 (Play) ]
                              │
                              ▼
           Smooth, Unbroken 20ms Playout Clock
```

### Jitter Buffer Algorithm Comparison

```
+-------------------+-----------------------------+-------------------------------+
| Strategy          | Strengths                   | Weaknesses                    |
+-------------------+-----------------------------+-------------------------------+
| Fixed Buffer      | Dead-simple implementation; | Adds static latency penalty   |
| (40ms - 60ms)     | zero CPU overhead.          | even on pristine connections. |
+-------------------+-----------------------------+-------------------------------+
| Adaptive Buffer   | Expands during congestion;  | Complex clock drift           |
| (RFC 3550 Compl.) | shrinks during stability.   | compensation logic required.  |
+-------------------+-----------------------------+-------------------------------+
| Aggressive Drop   | Enforces <400ms hard cap;   | Audio artifacts during severe |
| (Voice AI Bias)   | drops late frames entirely. | packet burst scenarios.       |
+-------------------+-----------------------------+-------------------------------+
```

### Adaptive Delay Formula

Track packet arrival jitter continuously using the standard IETF RFC 3550 algorithm:

$$D(i, j) = (R_j - S_j) - (R_i - S_i)$$

$$J(i) = J(i-1) + \frac{|D(i-1, i)| - J(i-1)}{16}$$

* Where $S_i$ is the sender timestamp of packet $i$, and $R_i$ is the local receiver arrival timestamp.
* Compute the dynamic target playout delay $D_{\text{playout}}$ dynamically:

$$D_{\text{playout}} = \text{Average Network Delay} + (2 \times J)$$

If $D_{\text{playout}} > 80\text{ms}$, hard-cap the jitter buffer at 80ms and drop straggling frames. In conversational voice AI, an audio frame that arrives too late is useless; dropping it immediately and using Opus Packet Loss Concealment (PLC) preserves conversational turn flow far better than introducing playout lag.

---

## 7. Production Verification & Latency Checklist

Use this checklist to benchmark your infrastructure before deploying agents into production:

```
[ ] AUDIO CAPTURE & FRAMING
    [ ] Audio stream is strictly packaged into 20ms or 32ms non-overlapping frames.
    [ ] Audio format entering the VAD engine is 16-bit Linear PCM (8kHz or 16kHz mono).
    [ ] Opus encoder flags configured: application=voip, cbr=true, useinbandfec=true, dtx=false.

[ ] NETWORK & TRANSPORT
    [ ] Client-to-server connection established via WebRTC Data/Media tracks or UDP-backed SIP.
    [ ] Server-side ingress endpoints are co-located within 30ms RTT of inference backends.
    [ ] TCP fallback disabled or strictly prioritized behind UDP/ICE candidates.

[ ] VOICE ACTIVITY DETECTION (VAD)
    [ ] VAD neural inference runs locally in-process via ONNX Runtime (<2ms execution per frame).
    [ ] Silence-to-turn-commit window tuned between 80ms and 120ms.
    [ ] Pre-roll circular memory buffer stores 100ms - 150ms of audio preceding trigger.

[ ] INTERRUPTION & BARGE-IN
    [ ] User speech detection immediately cancels active LLM generation via an AbortController.
    [ ] Playout jitter buffer immediately flushes all pending egress audio upon barge-in trigger.
    [ ] STT state machine drops downstream audio transcripts emitted while agent was speaking.

[ ] INFERENCE BENCHMARKING
    [ ] Streaming STT yields partial/final transcript within 100ms of VAD turn-commit.
    [ ] LLM inference engine delivers Time-To-First-Token (TTFT) in <= 120ms (e.g., Groq / vLL
