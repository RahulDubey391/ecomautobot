# Module 4: Voice UX Benchmarks, Echo Cancellation & Per-Minute Cost Calculator

## 1. Latency & Audio Quality Benchmark Suite

Achieving human-parity conversational voice agents requires strictly budgeting latency across every hop in the pipeline. Human conversation operates with an optimal inter-turn pause of 200 ms to 450 ms. When conversational turn-taking exceeds 600 ms, users perceive hesitation; beyond 800 ms, users routinely experience conversational collisions, double-talking, and voice frustration.

### Target KPI SLA Table

| Pipeline Component | Exceptional (Tier 1) | Production Acceptable | Degraded / Action Required | Measurement Methodology |
| :--- | :--- | :--- | :--- | :--- |
| **Inbound VAD Trim (Stop-of-Speech)** | 120 ms - 180 ms | 200 ms - 280 ms | > 350 ms | Silence delta detection timestamp minus last vocal formant energy packet. |
| **PSTN / WebRTC Ingestion Ingress** | 15 ms - 30 ms | 35 ms - 60 ms | > 85 ms | Audio frame packet arrival at edge gateway minus edge client RTP timestamp. |
| **Streaming ASR First-Partial Latency** | 80 ms - 140 ms | 150 ms - 220 ms | > 300 ms | Websocket frame emission timestamp minus final voice frame arrival. |
| **LLM Time-to-First-Token (TTFT)** | 120 ms - 250 ms | 260 ms - 450 ms | > 650 ms | HTTP/Websocket token yield chunk #1 minus context dispatch termination. |
| **TTS Time-to-First-Chunk (TTFC)** | 60 ms - 120 ms | 130 ms - 200 ms | > 300 ms | PCM frame 1 received from TTS engine minus token emission into TTS buffer. |
| **Jitter Buffer & Playback Ingress** | 20 ms - 40 ms | 45 ms - 80 ms | > 120 ms | Local audio driver DAC tick minus buffer packet push event. |
| **Total Voice-to-Voice Latency** | **415 ms - 760 ms** | **770 ms - 1,100 ms** | **> 1,200 ms** | End of human speech to start of synthetic speaker audio (glass-to-glass). |
| **PESQ Score (Perceptual Voice Quality)**| 4.2 - 4.5 | 3.8 - 4.1 | < 3.5 | ITU-T P.862 wideband evaluation against source WAV files. |
| **POLQA Score (Super-wideband / VoLTE)**| 4.3 - 4.8 | 4.0 - 4.2 | < 3.8 | ITU-T P.863 evaluation over Opus 48 kHz / G.711u codecs. |

---

### Automated Latency Instrumentation Script

Deploy this Node.js benchmark client directly inside your edge orchestrator to track micro-latencies across VAD, ASR, LLM, and TTS streams.

```typescript
// latency-auditor.ts
import { performance } from "perf_hooks";

export interface LatencyTrace {
  sessionId: string;
  turnIndex: number;
  t_user_silence_detected: number;
  t_asr_final_transcript: number;
  t_llm_first_token: number;
  t_llm_final_token: number;
  t_tts_first_audio_chunk: number;
  t_client_playback_start: number;
}

export class LatencyTracer {
  private traces: Map<string, LatencyTrace> = new Map();

  public startTurn(sessionId: string, turnIndex: number, userSilenceTimestamp: number = performance.now()): void {
    this.traces.set(`${sessionId}:${turnIndex}`, {
      sessionId,
      turnIndex,
      t_user_silence_detected: userSilenceTimestamp,
      t_asr_final_transcript: 0,
      t_llm_first_token: 0,
      t_llm_final_token: 0,
      t_tts_first_audio_chunk: 0,
      t_client_playback_start: 0,
    });
  }

  public markAsrFinal(sessionId: string, turnIndex: number): void {
    const trace = this.traces.get(`${sessionId}:${turnIndex}`);
    if (trace) trace.t_asr_final_transcript = performance.now();
  }

  public markLlmFirstToken(sessionId: string, turnIndex: number): void {
    const trace = this.traces.get(`${sessionId}:${turnIndex}`);
    if (trace) trace.t_llm_first_token = performance.now();
  }

  public markLlmFinalToken(sessionId: string, turnIndex: number): void {
    const trace = this.traces.get(`${sessionId}:${turnIndex}`);
    if (trace) trace.t_llm_final_token = performance.now();
  }

  public markTtsFirstChunk(sessionId: string, turnIndex: number): void {
    const trace = this.traces.get(`${sessionId}:${turnIndex}`);
    if (trace) trace.t_tts_first_audio_chunk = performance.now();
  }

  public markPlaybackStart(sessionId: string, turnIndex: number): void {
    const trace = this.traces.get(`${sessionId}:${turnIndex}`);
    if (trace) {
      trace.t_client_playback_start = performance.now();
      this.publishReport(trace);
    }
  }

  private publishReport(trace: LatencyTrace): void {
    const asrDuration = trace.t_asr_final_transcript - trace.t_user_silence_detected;
    const llmTTFT = trace.t_llm_first_token - trace.t_asr_final_transcript;
    const ttsTTFC = trace.t_tts_first_audio_chunk - trace.t_llm_first_token;
    const edgeTransport = trace.t_client_playback_start - trace.t_tts_first_audio_chunk;
    const glassToGlass = trace.t_client_playback_start - trace.t_user_silence_detected;

    const metrics = {
      sessionId: trace.sessionId,
      turnIndex: trace.turnIndex,
      asr_duration_ms: Number(asrDuration.toFixed(2)),
      llm_ttft_ms: Number(llmTTFT.toFixed(2)),
      tts_ttfc_ms: Number(ttsTTFC.toFixed(2)),
      transport_ms: Number(edgeTransport.toFixed(2)),
      total_glass_to_glass_ms: Number(glassToGlass.toFixed(2)),
      breaches_sla: glassToGlass > 800.0,
    };

    console.log(`[LATENCY-AUDIT] ${JSON.stringify(metrics)}`);
    this.traces.delete(`${trace.sessionId}:${trace.turnIndex}`);
  }
}
```

---

## 2. Acoustic Echo Cancellation (AEC) & Barge-In Blueprint

Barge-in fails when an open microphone captures the synthetic voice played over the user's loudspeaker, feeding it back into the ASR pipeline as a new user interruption. The system interrupts its own speech, stuttering infinitely.

### Signal Chain: Raw Audio Ingest to Hardware Playback

```
+-------------------------------------------------------------------------------+
|                             CLIENT / HARDWARE EDGE                            |
|                                                                               |
|  [Microphone] ---> (AEC Block: Near-End Mic MINUS Echo Ref) ---> Inbound RTP  |
|         ^                               |                                     |
|         | Acoustic Coupling             |                                     |
|         | Path                          v                                     |
|  [Loudspeaker] <--- [Jitter Buffer] <--- Loopback Reference <--- Outbound RTP |
+-------------------------------------------------------------------------------+
                                                                 |
+-------------------------------------------------------------------------------+
|                            SERVER / CLOUD PIPELINE             |
|                                                                v
|  WebRTC Inbound -> Silero VAD Core -> Dynamic Gate -> Streaming ASR Engine    |
|                          |                   |                                |
|                          | Interruption      +-- (Suppress if Outbound Active |
|                          v Detected              & Vol < Cancellation Thresh) |
|               [Abort Signal / Flush Buffer]                                   |
|                          |                                                    |
|                          +-----------------> Clears Server Outbound Buffer    |
|                          +-----------------> Sends WebSocket 0x09 Clear Frame |
+-------------------------------------------------------------------------------+
```

### WebRTC AEC3 Production Constraint Configuration

Pass this configuration to the WebRTC user media request on web and mobile endpoints:

```javascript
// webrtc-audio-constraints.js
export const productionAudioConstraints = {
  audio: {
    channelCount: { ideal: 1 },
    sampleRate: { ideal: 48000 },
    sampleSize: { ideal: 16 },
    echoCancellation: { exact: true },
    noiseSuppression: { exact: true },
    autoGainControl: { exact: true },
    // Vendor-specific WebRTC engine overrides
    googEchoCancellation: { exact: true },
    googAutoGainControl: { exact: true },
    googNoiseSuppression: { exact: true },
    googHighpassFilter: { exact: true },
    googTypingNoiseDetection: { exact: true },
    voiceIsolation: { ideal: true }
  }
};
```

---

### Dual-Threshold Voice Activity Detector (VAD) Implementation

This Python service runs at your edge processing layer, consuming 20 ms linear PCM16 chunks (640 bytes at 16 kHz) and implementing stateful dynamic gating to prevent false interruptions.

```python
# dynamic_vad_interrupter.py
import numpy as np
import collections
from typing import Generator, Optional

class BargeInVADDetector:
    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 20,
        idle_threshold: float = 0.50,
        barge_threshold: float = 0.85,
        required_consecutive_frames: int = 3
    ):
        self.sample_rate = sample_rate
        self.frame_size = int(sample_rate * (frame_duration_ms / 1000.0))
        self.idle_threshold = idle_threshold
        self.barge_threshold = barge_threshold
        self.required_consecutive = required_consecutive_frames
        
        self.consecutive_speech_frames = 0
        self.is_agent_speaking = False
        
        # Audio ring buffer for pre-roll packet retrieval
        self.pre_roll_buffer = collections.deque(maxlen=10)

    def set_agent_speaking_state(self, speaking: bool) -> None:
        """Update system state when outbound TTS frames are actively playing."""
        self.is_agent_speaking = speaking
        if not speaking:
            self.consecutive_speech_frames = 0

    def compute_energy(self, pcm_data: bytes) -> float:
        """Calculate Root Mean Square (RMS) to ignore noise floor blips."""
        samples = np.frombuffer(pcm_data, dtype=np.int16)
        if len(samples) == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples.astype(np.float64)**2)))

    def evaluate_frame(
        self, 
        pcm_bytes: bytes, 
        mock_silero_score: Optional[float] = None
    ) -> dict:
        """
        Accepts 20ms of PCM16 audio. Evaluates whether barge-in occurred.
        Returns payload dict indicating speech presence and interrupt signal.
        """
        if len(pcm_bytes) != self.frame_size * 2:
            raise ValueError(f"Expected frame length {self.frame_size * 2} bytes, received {len(pcm_bytes)}")

        self.pre_roll_buffer.append(pcm_bytes)
        
        # In production, pass pcm_bytes to real Silero VAD ONNX model
        # mock_silero_score simulated here for structural interface execution
        vad_probability = mock_silero_score if mock_silero_score is not None else 0.0
        frame_rms = self.compute_energy(pcm_bytes)

        # Dynamic Threshold Activation
        active_threshold = self.barge_threshold if self.is_agent_speaking else self.idle_threshold
        
        # Secondary condition: Ensure absolute energy exceeds standard mic acoustic bleed
        is_speech = (vad_probability >= active_threshold) and (frame_rms > 350.0)

        if is_speech:
            self.consecutive_speech_frames += 1
        else:
            self.consecutive_speech_frames = max(0, self.consecutive_speech_frames - 1)

        barge_in_triggered = False
        if self.consecutive_speech_frames >= self.required_consecutive:
            if self.is_agent_speaking:
                barge_in_triggered = True
                self.is_agent_speaking = False  # Reset on trip
            
        return {
            "vad_score": vad_probability,
            "rms_level": frame_rms,
            "speech_active": self.consecutive_speech_frames >= self.required_consecutive,
            "trigger_barge_in": barge_in_triggered,
            "pre_roll_audio": b"".join(self.pre_roll_buffer) if barge_in_triggered else b""
        }
```

---

## 3. Realtime Recovery Playbooks

When network jitter, model rate-limits, or streaming dropouts occur, voice bots must fail gracefully without leaving callers stranded in dead silence.

### Recovery State Machine

```
              +----------------------------+
              | Voice Interaction Loop     |
              +----------------------------+
                             |
             [Pipeline Timeout / Fail Event]
                             |
         +-------------------+-------------------+
         |                                       |
    (TTS Server)                            (LLM Server)
  Unreachable / 500                      Drop / 429 / TTFT > 800ms
         |                                       |
         v                                       v
[Play Pre-rendered Telephony]           [Inject Conversational Filler]
"I missed that. One moment?"            "Let's see..." / "Hmm..."
         |                                       |
         +-------------------+-------------------+
                             |
                     [Engine Recovered?]
                       /           \
                     YES            NO
                     /               \
       [Resume Live Stream]    [Fallback Provider Trigger]
                                      |
                              (Deepgram -> OpenAI /
                               Cartesia -> ElevenLabs)
                                      |
                                [Total Failure]
                                      |
                                      v
                             [PSTN SIP Transfer]
                             To Live Agent Desk
```

---

### Deterministic Failure Playbook Matrix

| Failure Mode | Trigger Condition | System Action | Auditory Output (Played to Caller) |
| :--- | :--- | :--- | :--- |
| **PSTN Packet Loss** | RTP packet loss > 18% for 4 seconds | Switch to G.711u PLC (Packet Loss Concealment), force Jitter buffer to 120 ms. | *[Micro-suppression; no audio artifact injected]* |
| **ASR Stream Drop** | WebSocket close code `1006` or idle frame silence > 8000 ms | Re-initialize stream immediately; route cached buffer through secondary fallback ASR. | "I'm having a little trouble hearing you. Could you repeat that?" |
| **LLM Inference 429** | Upstream API returns HTTP 429 or WebSocket Engine Exhaustion | Fallback immediately to fast local small-footprint model (e.g., Llama-3-8B on vLLM edge). | *[No verbal apology; seamless execution via lower parameter fallback]* |
| **LLM High Latency** | Time-to-First-Token exceeds 700 ms threshold | Play random non-blocking filler utterance from local memory instantly. | "Hmm, let me check that for you..." |
| **TTS Synthesis Failure** | WebSocket handshake drop or HTTP 504 on audio chunk #1 | Stream pre-rendered PCM audio from local static edge cache. | "One second, I'm pulling up your details." |
| **Catastrophic Crash** | Multi-system timeout: total silence exceeds 4.5 seconds | Send SIP REFER transfer packet to human backup queue. | "Please hold while I get an agent on the line." |

---

### Low-Latency Conversational Filler Dispatcher

```typescript
// filler-dispatcher.ts
import { EventEmitter } from "events";

export class LowLatencyFillerManager extends EventEmitter {
  private timer: NodeJS.Timeout | null = null;
  private readonly thresholdMs: number;
  private isProcessing: boolean = false;
  
  // Audio caches pre-rendered as raw mu-law (8kHz) for Twilio, or PCM16 for WebRTC
  private fillerLibrary: Array<{ id: string; text: string; audioBytes: Buffer }> = [];

  constructor(thresholdMs: number = 700) {
    super();
    this.thresholdMs = thresholdMs;
    this.loadFillerCache();
  }

  private loadFillerCache(): void {
    // Hard-coded payload simulating pre-rendered 8kHz mu-law audio
    this.fillerLibrary = [
      { id: "f1", text: "Hmm...", audioBytes: Buffer.alloc(3200, 0xff) },
      { id: "f2", text: "Let's see...", audioBytes: Buffer.alloc(4800, 0x7f) },
      { id: "f3", text: "Just a second...", audioBytes: Buffer.alloc(6400, 0xaa) },
    ];
  }

  public onUserFinishedSpeaking(): void {
    this.isProcessing = true;
    this.timer = setTimeout(() => {
      if (this.isProcessing) {
        this.dispatchRandomFiller();
      }
    }, this.thresholdMs);
  }

  public onFirstTokenReceived(): void {
    this.isProcessing = false;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private dispatchRandomFiller(): void {
    const randomIndex = Math.floor(Math.random() * this.fillerLibrary.length);
    const selectedFiller = this.fillerLibrary[randomIndex];
    
    // Emit the pre-rendered audio buffer directly down outbound channel
    this.emit("play_immediate_chunk", {
      type: "audio/x-mulaw",
      payload: selectedFiller.audioBytes,
      transcript: selectedFiller.text
    });
  }
}
```

---

## 4. Voice UX Audit Checklist

Execute this verification protocol before deploying any real-time conversational release.

```markdown
### Pre-Flight Voice Bot Audit Checklist

#### Phase 1: Barge-In & Acoustic Performance
- [ ] **Dual-Channel Echo Isolation:** Does playing 85 dB voice output through typical device speakers trigger false ASR transcriptions?
- [ ] **Mid-Sentence Interruption Delay:** From the instant an interruption word (e.g., "Stop") hits the microphone, does system audio playback drop within <= 180 ms?
- [ ] **Noise Floor Rejection:** Verify that background mechanical noise (keyboard tapping, ambient traffic, office chatter at 50 dB) does not initiate an ASR turn.
- [ ] **Pre-Roll Audio Recovery:** When interrupting, are the 200 ms of audio preceding the VAD trigger preserved so the user's first word is not clipped?

#### Phase 2: Latency SLAs (Glass-to-Glass)
- [ ] **VAD Cutoff Precision:** Confirm stop-of-speech window triggers between 180 ms and 250 ms.
- [ ] **LLM Time-to-First-Token (TTFT):** Confirm P95 TTFT is < 300 ms under a concurrent load of 50 calls.
- [ ] **TTS First-Audio-Chunk Delivery:** Confirm streaming audio chunk 1 begins arriving at the client <= 120 ms post-token yield.
- [ ] **Network Ingress Drift:** Under simulated 80 ms packet jitter and 5% loss, confirm jitter buffers do not add > 60 ms buffer lag.

#### Phase 3: Conversational Voice Tone & Pronunciation
- [ ] **Number Parsing:** Are numbers, currency, dates, and order codes read fluently (e.g., "$120.50" pronounced "one hundred twenty dollars and fifty cents," "ID-883" spelled phonetically)?
- [ ] **SSML/Engine Breath Ingestion:** Ensure sentence starts are natural and lack mechanical "pops" or DC offset clicks.
- [ ] **Hallucination Containment:** Verify the system outputs brief, spoken-length phrases (1 to 2 sentences per turn) rather than multi-paragraph walls of text.

#### Phase 4: Network & Hardware Edge Fallbacks
- [ ] **WebSocket Interruption Resiliency:** Does the pipeline survive abrupt network drops without memory leakage on the server?
- [ ] **Fallback TTS Latency Guarantee:** If the primary streaming TTS fails, does the fallback engine return valid audio within <= 400 ms?
- [ ] **SIP/PSTN Bridging:** Ensure automatic transfer to an external phone number executes cleanly using standard SIP REFER protocols within 1.5 seconds.
```

---

## 5. Per-Minute Cost Calculator & Telephony Unit Economics

Building high-performance voice infrastructure requires tracking unit costs per conversation minute across five core cost layers.

### Infrastructure Cost Models (Per-Minute Breakdown)

1. **Telephony Layer:** Inbound/Outbound SIP trunking or WebRTC server egress.
2. **ASR (Speech-to-Text):** Streaming transcription engine.
3. **LLM Inference:** Compute pricing based on tokens-in and tokens-out per turn.
4. **TTS (Text-to-Speech):** Character-based audio generation cost.
5. **Hosting & Orchestration Edge:** Compute instances managing WebRTC media and routing logic.

#### Typical Conversational Turn Characteristics (Per 1.0 Minute of Realtime Interaction)
* **Average Conversational Turns:** 4 to 6 turns per minute.
* **Human Speaking Time:** ~25 seconds per minute (ASR input consumption).
* **Bot Speaking Time:** ~25 seconds per minute (TTS output generation).
* **Silence/Processing Windows:** ~10 seconds per minute.
* **Token Profile:**
  * System Prompt + History: ~1,200 tokens cached baseline.
  * User Inbound (ASR): ~60 words -> ~80 tokens.
  * Agent Outbound (TTS): ~75 words -> ~100 tokens generated (~450 characters).

---

### Comparative Cost Table (5 Provider Stacks)

| Provider Architecture Stack | Telephony (Per Min) | ASR (Per Min) | LLM (Avg 6 Turns/Min) | TTS (Per Min) | Core Server / Gateway | Total Cost / Minute | Cost / 1,000 Minutes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Stack A: Premium Hyperscaler**<br>(Twilio + Deepgram Nova-2 + GPT-4o + ElevenLabs Flash) | $0.0040 (SIP) | $0.0043 (Deepgram) | $0.0250 (GPT-4o standard) | $0.0240 (ElevenLabs @ 450 chars) | $0.0050 (AWS Fargate) | **$0.0623** | **$62.30** |
| **Stack B: Optimized Realtime Direct**<br>(Telnyx + OpenAI Realtime API via WebRTC) | $0.0035 (Telnyx) | Integrated | $0.0600 (Audio In/Out direct) | Integrated | $0.0030 (Fly.io edge) | **$0.0665** | **$66.50** |
| **Stack C: Cost-Performance Balance**<br>(Twilio Trunk + Deepgram Nova-2 + Claude 3.5 Sonnet + Cartesia Sonic) | $0.0040 (Twilio) | $0.0043 (Deepgram) | $0.0085 (Sonnet 3.5) | $0.0068 (Cartesia @ 450 chars) | $0.0040 (Fly.io edge) | **$0.0276** | **$27.60** |
| **Stack D: Low-Latency High-Efficiency**<br>(Telnyx + Deepgram Nova-2 + Groq Llama-3.3-70B + Cartesia Sonic) | $0.0035 (Telnyx) | $0.0043 (Deepgram) | $0.0012 (Groq compute) | $0.0068 (Cartesia) | $0.0030 (Hetzner Node) | **$0.0188** | **$18.80** |
| **Stack E: Self-Hosted Sovereign**<br>(Direct Carrier SIP + Whisper (vLLM) + Llama-3-8B + StyleTTS2) | $0.0020 (Pure Carrier) | $0.0018 (GPU amortized) | $0.0022 (GPU amortized) | $0.0015 (GPU amortized) | $0.0010 (Dedicated Bare-metal) | **$0.0085** | **$8.50** |

---

### Per-Minute Cost Model Calculator

Run this Node.js utility directly in your CI pipeline, financial model, or production dashboard to forecast operational margins based on your actual pipeline composition.

```typescript
// cost-calculator.ts

export interface UnitCostProfile {
  name: string;
  telephonyPerMinute: number;
  asrPerMinute: number;
  llmInputPerMillionTokens: number;
  llmOutputPerMillionTokens: number;
  ttsPerThousandCharacters: number;
  hostingPerMinute: number;
}

export interface ConversationTurnProfile {
  turnsPerMinute: number;
  averageInputTokensPerTurn: number;
  averageOutputTokensPerTurn: number;
  averageTtsCharsPerTurn: number;
}

export class VoiceCostCalculator {
  public static calculateCostPerMinute(
    profile: UnitCostProfile,
    conversation: ConversationTurnProfile
  ): {
    telephonyCost: number;
    asrCost: number;
    llmCost: number;
    ttsCost: number;
    hostingCost: number;
    totalPerMinuteCost: number;
    projectedCost10kMinutes: number;
  } {
    const totalInputTokens = conversation.turnsPerMinute * conversation.averageInputTokensPerTurn;
    const totalOutputTokens = conversation.turnsPerMinute * conversation.averageOutputTokensPerTurn;
    const totalTtsChars = conversation.turnsPerMinute * conversation.averageTtsCharsPerTurn;

    const telephonyCost = profile.telephonyPerMinute;
    const asrCost = profile.asrPerMinute;
    const llmCost = 
      (totalInputTokens / 1_000_000) * profile.llmInputPerMillionTokens +
      (totalOutputTokens / 1_000_000) * profile.llmOutputPerMillionTokens;
    const ttsCost = (totalTtsChars / 1_000) * profile.ttsPerThousandCharacters;
    const hostingCost = profile.hostingPerMinute;

    const totalPerMinuteCost = telephonyCost + asrCost + llmCost + ttsCost + hostingCost;

    return {
      telephonyCost: Number(telephonyCost.toFixed(5)),
      asrCost: Number(asrCost.toFixed(5)),
      llmCost: Number(llmCost.toFixed(5)),
      ttsCost: Number(ttsCost.toFixed(5)),
      hostingCost: Number(hostingCost.toFixed(5)),
      totalPerMinuteCost: Number(totalPerMinuteCost.toFixed(4)),
      projectedCost10kMinutes: Number((totalPerMinuteCost * 10_000).toFixed(2)),
    };
  }
}

// Concrete execution example comparing typical production configurations:
const stackOptimized: UnitCostProfile = {
  name: "Groq-Cartesia-Telnyx-Stack",
  telephonyPerMinute: 0.0035,
  asrPerMinute: 0.0043,
  llmInputPerMillionTokens: 0.59,
  llmOutputPerMillionTokens: 0.79,
  ttsPerThousandCharacters: 0.015,
  hostingPerMinute: 0.003,
};

const conversationProfile: ConversationTurnProfile = {
  turnsPerMinute: 5,
  averageInputTokensPerTurn: 250,   // System prompt context + user input
  averageOutputTokensPerTurn: 45,    // Terse, high-speed spoken returns
  averageTtsCharsPerTurn: 90,        // Conversational voice turns
};

const financialProjection = VoiceCostCalculator.calculateCostPerMinute(stackOptimized, conversationProfile);
console.log("Financial Unit Economics Report:", JSON.stringify(financialProjection, null, 2));
```

---

## 6. Zero-Drift Production Rules

1. **Always Kill Audio on First Packet:** When an interruption is confirmed by the dynamic VAD, emit an explicit flush/cancellation control signal immediately. Do not wait for the speech-to-text pipeline to transcribe the barge-in phrase before cutting off outbound audio.
2. **Never Buffer Indefinitely:** Configure client-side audio jitter buffers to drop frames when jitter exceeds 120 ms. Maintaining voice synchronicity is strictly superior to preserving degraded audio frames.
3. **Bind Context Length:** Enforce a hard cap on your LLM chat context buffer (maximum 10 conversational turns) via an aggressive rolling summarization strategy. As inbound tokens scale, prompt processing latency increases, causing glass-to-glass turn delays to slip out of your target latency SLA.
