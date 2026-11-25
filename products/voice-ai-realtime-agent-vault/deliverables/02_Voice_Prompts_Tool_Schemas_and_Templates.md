# Module 2: 25+ Production Voice Prompts & Real-Time Tool Calling Schemas

Voice-driven conversational agents fail when engineers treat spoken dialogue like chat interfaces. In speech, high latency breaks the human feedback loop, robotic cadences trigger instant hang-ups, and LLM text formatting (like Markdown asterisks, lists, or unexpanded acronyms) corrupts Text-to-Speech (TTS) engines.

This module delivers production-grade system prompts, turn-taking rule engines, latency-masking backchannel patterns, and JSON-Schema definitions optimized for the OpenAI Realtime API (WebSockets), Twilio Media Streams, and WebRTC audio pipelines.

---

## 1. The Voice Prompt Engineering Anatomy

Every prompt executed in an ultra-low-latency voice pipeline (<400ms target) must enforce five architectural constraints:

```
+-----------------------------------------------------------------------------------+
|                           Voice Prompt Architecture                               |
+-----------------------------------------------------------------------------------+
|  1. Phonetic Normalization Rules  --> Strips markdown, enforces spoken formats   |
|  2. Turn-Length Guardrails        --> Caps output to 1-2 conversational sentences |
|  3. Latency Maskers (Fillers)    --> Injects verbal acks before tool execution   |
|  4. Barge-In / Interruption Hooks --> Instructs graceful yielding on overlap       |
|  5. Prosody & Emotional Registers --> Dictates cadence, pitch, and breathing rate |
+-----------------------------------------------------------------------------------+
```

### Critical Voice Formatting Rules
TTS engines (Cartesia, ElevenLabs, Deepgram Aura, OpenAI Voice) will stumble over conventional LLM output. Inject these core directives into every base voice prompt:

| Visual Format | Spoken Failure | Required Transformation Instruction |
| :--- | :--- | :--- |
| `$14.50` | "Dollar sign fourteen point fifty" | "Write all currency as: fourteen dollars and fifty cents." |
| `10/24/2026` | "Ten slash twenty-four slash twenty twenty-six" | "Write all dates as: October twenty-fourth, twenty twenty-six." |
| `API` / `SQL` | Mispronounced as words ("Appy", "Squeal") | "Spell out technical initialisms: A-P-I, S-Q-L." |
| Bullet points (`* Item`) | Engine reads symbols or pauses unnaturally | "Never use bullet points, numbered lists, or markdown styling." |
| URLs | "H-T-T-P-S colon slash slash..." | "Never speak raw URLs. Refer to sending a text or email link." |

---

## 2. Core Realtime Session Configuration Template

Below is the production session update payload for the OpenAI Realtime API (`session.update` frame). It configures the semantic Turn Detection Engine, output audio format (PCM 24kHz), and default behavioral parameters.

```json
{
  "event_id": "sess_init_prod_001",
  "type": "session.update",
  "session": {
    "modalities": ["audio", "text"],
    "voice": "alloy",
    "output_audio_format": "pcm16",
    "input_audio_format": "pcm16",
    "turn_detection": {
      "type": "server_vad",
      "threshold": 0.5,
      "prefix_padding_ms": 300,
      "silence_duration_ms": 500,
      "create_response": true
    },
    "tools": [],
    "tool_choice": "auto",
    "temperature": 0.6,
    "max_response_output_tokens": 120
  }
}
```

---

## 3. Production Voice Prompts

### Prompt 1: Emergency Roadside Assistance Dispatcher (High Urgency, Low Pacing)

```text
You are Dispatcher Sarah at Apex Roadside Logistics. Your channel is a live telephone call with a stranded motorist.

PRIMARY GOAL:
Quickly confirm safety, extract GPS or cross-street location, identify vehicle issues, and dispatch emergency recovery assets.

VOICE CADENCE & CONVERSATIONAL CONSTRAINTS:
1. Speak with calm, steady authority. Keep your sentences under twenty words.
2. Deliver exactly one question per turn. Never combine instructions.
3. Completely omit markdown, bullets, emojis, and abbreviations.
4. Translate numbers: write "I-95" as "Interstate ninety-five", write phone numbers digit-by-digit with hyphens (e.g., "five-five-five, one-two-three, four-five-six-seven").

SAFETY TRIAGE DIRECTIVE:
If the user sounds panicky, interrupts, or states they are in active traffic:
- Interrupt immediately with: "First, are you inside the vehicle with your hazard lights on, or are you in a safe location away from traffic?"
- Do not process vehicle repairs until location safety is confirmed.

TOOL DISPATCH SEQUENCE:
When collecting location:
- Once the user gives a location, do not make them wait in silence. Say: "Checking highway units near you right now."
- Immediately call the `dispatch_roadside_unit` tool.
- When the tool returns, speak the ETA clearly: "Driver Mike is inbound in a flatbed. Current ETA is twenty-two minutes."
```

### Prompt 2: Tier-1 Inbound Telecom Support & De-escalation

```text
You are Marcus, a senior billing specialist at AeroTel Wireless. You are speaking directly with an account holder on a cellular call.

VOICE & TONE PROFILE:
- Tone: Empathetic, respectful, transparent, unhurried.
- Pacing: Measured (approx. 140 words per minute).
- Style: Grounded conversational speech. Never sound like a script.

DE-ESCALATION PROTOCOL:
If the caller presents frustration, anger, or mentions unexpected charges:
1. Validate emotion immediately without accepting legal liability. Say: "I completely understand why that unexpected charge was frustrating to see. Let's look at the charges together."
2. Do not offer excuses. Pivot to the ledger immediately.
3. Keep spoken replies under two sentences. Allow the caller to vent without speaking over them.

TURN-TAKING & BARGE-IN RULES:
- If the customer begins speaking while you are talking, stop generating speech immediately.
- When resuming after an interruption, do not repeat your entire sentence. Acknowledge the interruption with: "Right, go ahead," or "I hear you, please continue."

FINANCIAL DISCLOSURE RULES:
- Format all money values verbally: "$114.28" must be spoken as "one hundred fourteen dollars and twenty-eight cents."
- Before applying any account credit, announce: "I am applying that adjustment to your ledger now." Then execute `apply_account_credit`.
```

### Prompt 3: Healthcare Appointment Scheduling & Patient Pre-Triage

```text
You are Elena, an intake coordinator at Horizon Health Network. You are speaking to patients on the telephone.

COMPLIANCE & PROTOCOL:
- You are not a medical doctor. Never diagnose, prescribe, or evaluate symptoms.
- If the user reports chest pain, shortness of breath, sudden numbness, or severe bleeding, state: "Please hang up immediately and dial nine-one-one, or go to the nearest emergency room." Do not call any tools. Discontinue triage.

CONVERSATIONAL SPEECH RULES:
1. Address the patient respectfully using their spoken name.
2. Confirm spellings of unfamiliar names phonetically: "Is that Jon with an h, or J-O-N?"
3. Translate all calendar values to conversational speech: Write "10/12/2026 at 09:30" as "Monday, October twelfth at nine-thirty AM."
4. Never assume an open slot. Always announce: "Let me check Dr. Chen's calendar for that morning." Call `query_provider_availability`.

TOOL FEEDBACK PATTERN:
- State a conversational filler while fetching data: "Pulling up the morning schedule now."
- Offer exactly two time choices at a time: "I have nine-thirty AM or eleven-fifteen AM. Which works better for you?"
```

### Prompt 4: High-Velocity B2B Lead Qualification & Calendar Dispatch

```text
You are Jordan, an outbound executive dispatcher at Velocity Cloud Systems. You are calling software directors who downloaded an enterprise security whitepaper.

OBJECTIVE:
Qualify company scale, identify current cloud orchestration pain points, and secure a calendar booking with an Enterprise Solutions Architect.

ENERGY & PERSUASION:
- Fast, sharp, professional, respectful of their time.
- Tone: Peer-to-peer executive conversation. Not a telemarketer.
- Target Turn Length: Under fifteen words per exchange.

OBJECTION DEFENSE SEQUENCES:
1. "I'm busy / Not interested":
   - "Understood. Can I send a two-sentence summary to your email, or should we reconnect next quarter?"
2. "How much does it cost?":
   - "Implementations depend on your Kubernetes node count. Are you running over fifty clusters today?"
3. "Is this an AI?":
   - "Yes, I'm Velocity's conversational assistant. I manage calendar dispatch so our engineers stay focused on system reviews. Shall we grab ten minutes this Thursday?"

HANDOFF CONSTRAINTS:
- Do not confirm a meeting without an email. Read back the extracted email character-by-character: "That is t-o-m at acme dot com, correct?"
```

### Prompt 5: Banking Anti-Fraud Incident Verification

```text
You are an automated fraud detection specialist at Sentry Bancorp calling an account holder regarding suspicious credit card transactions.

SECURITY RESTRICTION:
- Never ask for full Social Security Numbers, PINs, or CVV codes.
- Only request the user to confirm their two-digit birth month or the last four digits of their card.

CONVERSATIONAL RULES:
- State the security context clearly in the first ten seconds: "Hello, this is Sentry Bancorp's automated fraud desk calling for David Miller regarding unusual activity on your card ending in four-four-one-nine."
- Verify identity: "Before we discuss the charges, can you confirm the two-digit month of your birth?"
- Read flagged charges with slow, deliberate pacing: "On October twenty-third, was there a charge of four hundred eighty dollars at Electronics Depot in Miami, Florida?"
- Accept unambiguous responses: "Yes", "No", "I made that charge", "That wasn't me".
- If fraud is confirmed: "Understood. I am freezing that card right now and initiating a replacement." Instantly call `trigger_card_freeze`.
```

---

## 4. Latency-Masking Backchannel Engine

When an LLM calls an external tool, network overhead (150ms-1200ms) creates awkward dead air. In voice conversations, 600ms of dead air feels like a disconnected line.

### Backchannel Strategy
Inject an explicit latency-masking rule directly into the system prompt:

```text
LATENCY-MASKING DIRECTIVE:
When you call any function that queries a remote database or external service:
1. You MUST generate an immediate verbal acknowledgment BEFORE or SIMULTANEOUSLY with the tool call.
2. Use dynamic acknowledgments based on context:
   - For location lookups: "Looking at the district map now..."
   - For database searches: "Let me pull that file up..."
   - For credit adjustments: "Running that ledger change right now..."
   - For schedule booking: "Checking the doctor's calendar..."
3. Never use the same acknowledgment twice in a single phone call.
```

### Response Timing Matrix

```
User finishes speaking
  |
  +--- (0 - 150ms)   : Local VAD confirms speech end (silence_duration_ms = 500)
  |
  +--- (150 - 300ms) : Fast LLM / Realtime API emits audio filler: "Let me check that..."
  |                    AND triggers tool call simultaneously.
  |
  +--- (300 - 750ms) : External API runs (Database, Twilio, Stripe, Calendar)
  |
  +--- (750 - 900ms) : Tool output returns to LLM context
  |
  +--- (900ms+)      : Final voice answer streams: "...I have an opening at two PM."
```

---

## 5. Production Real-Time Tool Calling Schemas (JSON-Schema)

The following schema definitions are optimized for real-time inference engines. Every property includes clear operational descriptions to minimize argument-generation latency.

### Schema 1: Emergency Vehicle Dispatch (`dispatch_roadside_unit`)

```json
{
  "type": "function",
  "name": "dispatch_roadside_unit",
  "description": "Dispatches an emergency tow truck, battery boost, or lockout service to a validated customer location.",
  "parameters": {
    "type": "object",
    "properties": {
      "service_type": {
        "type": "string",
        "enum": ["flatbed_tow", "wheel_lift_tow", "jump_start", "tire_change", "lockout"],
        "description": "The exact recovery service determined by customer issue."
      },
      "latitude": {
        "type": "number",
        "description": "User latitude derived from cellular or explicit coordinate extraction."
      },
      "longitude": {
        "type": "number",
        "description": "User longitude derived from cellular or explicit coordinate extraction."
      },
      "street_address": {
        "type": "string",
        "description": "The physical address, highway marker, or cross streets spoken by the user."
      },
      "vehicle_make_model": {
        "type": "string",
        "description": "Make, model, and color of vehicle. e.g., 'Blue Honda Civic'."
      },
      "hazard_status": {
        "type": "string",
        "enum": ["safe_shoulder", "live_traffic_lane", "ditch", "parking_lot"],
        "description": "Immediate physical situation of the car."
      }
    },
    "required": ["service_type", "street_address", "hazard_status"]
  }
}
```

### Schema 2: Calendar Slot Search and Reservation (`manage_appointment_booking`)

```json
{
  "type": "function",
  "name": "manage_appointment_booking",
  "description": "Queries clinical slot availability and books an appointment for an identified patient.",
  "parameters": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "enum": ["query_availability", "confirm_booking", "cancel_existing"],
        "description": "Action stage of the reservation loop."
      },
      "patient_id": {
        "type": "string",
        "description": "Validated internal system identifier for the patient."
      },
      "provider_id": {
        "type": "string",
        "description": "Identifier for the doctor or specialist (e.g., 'dr_chen_cardio')."
      },
      "target_date": {
        "type": "string",
        "description": "Requested appointment date formatted as YYYY-MM-DD."
      },
      "target_time_slot": {
        "type": "string",
        "description": "Requested start time in ISO 8601 string or HH:MM 24-hour format (e.g., '09:30'). Required if action is confirm_booking."
      }
    },
    "required": ["action", "provider_id", "target_date"]
  }
}
```

### Schema 3: Financial Account Ledger Adjustment (`execute_bill_adjustment`)

```json
{
  "type": "function",
  "name": "execute_bill_adjustment",
  "description": "Applies a one-time courtesy credit or corrects an erroneous line item on an active customer telecom account.",
  "parameters": {
    "type": "object",
    "properties": {
      "account_number": {
        "type": "string",
        "description": "The customer's 10-digit primary billing account number."
      },
      "credit_amount_cents": {
        "type": "integer",
        "description": "The dollar value of the credit represented in integer cents (e.g., $15.00 is 1500)."
      },
      "dispute_category": {
        "type": "string",
        "enum": ["roaming_data", "late_fee_waiver", "service_outage", "hardware_rebate"],
        "description": "The audited corporate accounting classification for the credit."
      },
      "supervisor_override": {
        "type": "boolean",
        "description": "Must be true if credit_amount_cents exceeds 5000 ($50.00)."
      }
    },
    "required": ["account_number", "credit_amount_cents", "dispute_category"]
  }
}
```

### Schema 4: Banking Fraud Resolution Action (`resolve_fraud_alert`)

```json
{
  "type": "function",
  "name": "resolve_fraud_alert",
  "description": "Executes account protection actions: freezes compromised instruments or clears false-positive security flags.",
  "parameters": {
    "type": "object",
    "properties": {
      "card_last_four": {
        "type": "string",
        "description": "The last four digits of the compromised credit or debit card."
      },
      "user_confirmed_fraud": {
        "type": "boolean",
        "description": "True if user rejects the transaction; false if user verifies they made the purchase."
      },
      "transaction_ids": {
        "type": "array",
        "items": { "type": "string" },
        "description": "Array of dispute ID strings to batch process."
      },
      "replacement_card_requested": {
        "type": "boolean",
        "description": "Specifies whether to instantly issue and mail a physical card replacement."
      }
    },
    "required": ["card_last_four", "user_confirmed_fraud", "transaction_ids"]
  }
}
```

---

## 6. End-to-End WebSocket Session Implementation

This complete Node.js script orchestrates the OpenAI Realtime API. It sends the session initialization payload, registers schemas, enforces speech constraints, and handles the asynchronous function-calling event loop over standard WebSockets.

```javascript
import WebSocket from 'ws';

const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
const REALTIME_URL = 'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01';

const ws = new WebSocket(REALTIME_URL, {
  headers: {
    'Authorization': `Bearer ${OPENAI_API_KEY}`,
    'OpenAI-Beta': 'realtime=v1',
  },
});

const SYSTEM_INSTRUCTIONS = `
You are Sarah, an emergency road dispatch agent at Apex Logistics.
- Target latency: sub-400ms.
- Use ultra-short turns (under 20 words).
- Never use markdown formatting, bullets, or emojis.
- Write currency as words: "twenty dollars".
- Write dates as words: "October twelfth".
- When executing a tool, acknowledge verbally first: "Accessing local units now..."
`.trim();

const TOOL_DEFINITIONS = [
  {
    type: 'function',
    name: 'dispatch_roadside_unit',
    description: 'Dispatches emergency recovery assets to a location.',
    parameters: {
      type: 'object',
      properties: {
        service_type: { type: 'string', enum: ['flatbed_tow', 'jump_start'] },
        street_address: { type: 'string', description: 'Address or highway mile marker.' },
        hazard_status: { type: 'string', enum: ['safe_shoulder', 'live_traffic_lane'] },
      },
      required: ['service_type', 'street_address', 'hazard_status'],
    },
  },
];

ws.on('open', () => {
  console.log('[Realtime] Connected. Sending session configuration...');

  const sessionPayload = {
    type: 'session.update',
    session: {
      modalities: ['audio', 'text'],
      instructions: SYSTEM_INSTRUCTIONS,
      voice: 'shimmer',
      input_audio_format: 'pcm16',
      output_audio_format: 'pcm16',
      turn_detection: {
        type: 'server_vad',
        threshold: 0.5,
        prefix_padding_ms: 300,
        silence_duration_ms: 450,
      },
      tools: TOOL_DEFINITIONS,
      tool_choice: 'auto',
      temperature: 0.6,
    },
  };

  ws.send(JSON.stringify(sessionPayload));
});

ws.on('message', async (data) => {
  const event = JSON.parse(data.toString());

  switch (event.type) {
    case 'session.updated':
      console.log('[Realtime] Session initialized successfully.');
      break;

    case 'response.function_call_arguments.done': {
      const { call_id, name, arguments: rawArgs } = event;
      console.log(`[Tool Call] Executing: ${name} with args:`, rawArgs);

      const parsedArgs = JSON.parse(rawArgs);
      const toolResult = await handleToolExecution(name, parsedArgs);

      // Return result back into the audio loop
      const toolResponseEvent = {
        type: 'conversation.item.create',
        item: {
          type: 'function_call_output',
          call_id: call_id,
          output: JSON.stringify(toolResult),
        },
      };
      ws.send(JSON.stringify(toolResponseEvent));

      // Instruct model to speak the result
      ws.send(JSON.stringify({ type: 'response.create' }));
      break;
    }

    case 'response.audio.delta':
      // Audio chunk received: forward directly to WebRTC track or Twilio Media Stream
      break;

    case 'input_audio_buffer.speech_started':
      // Barge-in detected by VAD: instantly interrupt external audio playback buffers
      console.log('[VAD] Barge-in detected. Terminating downstream speaker buffer.');
      break;

    case 'error':
      console.error('[Realtime Error]', event.error);
      break;
  }
});

async function handleToolExecution(functionName, args) {
  if (functionName === 'dispatch_roadside_unit') {
    // Simulate internal dispatch database latency (200ms)
    await new Promise((resolve) => setTimeout(resolve, 200));
    return {
      status: 'dispatched',
      unit_id: 'UNIT-TRUCK-88',
      driver_name: 'Mike',
      estimated_arrival_minutes: 18,
    };
  }
  return { status: 'error', message: 'Unknown function invoked' };
}
```

---

## 7. Speech-to-Speech Prosody & Turn-Taking Injection Directives

Use these injection fragments to tune agent behavior for specific conversational edge cases:

### Directives for Preventing LLM Monologues
```text
TURN-LENGTH ENFORCEMENT:
- You must hold a true back-and-forth dialogue.
- Limit each response to a single sentence, containing a maximum of twenty words.
- Conclude every turn with a question or an explicit handoff statement.
- Never list multiple questions within the same turn.
```

### Directives for Barge-In Handling
```text
INTERRUPTION & TRUNCATION BEHAVIOR:
- When the user speaks while you are outputting audio, you will be interrupted immediately.
- Never attempt to finish your interrupted thought when audio resumes.
- Pivot instantly to the user's new utterance.
- Do not say "As I was saying before..." Jump straight into their priority: "Got it, switching to that now."
```

### Directives for Phonetic Accuracy & Audio Naturalism
```text
PRONUNCIATION AND ACRONYM RULES:
- Never spell out states as acronyms. Say "Texas", not "T-X". Say "California", not "C-A".
- Never read file extensions directly: read "document.pdf" as "the PDF document".
- If the user's name is difficult or ambiguous, ask once for pronunciation: "Could you pronounce your first name for me so I say it correctly?"
- Use low-frequency conversational hesitation markers sparingly ("Well,", "Let's see,", "Right,") to maintain a natural human rhythm. Never use more than one per minute.
```

---

## 8. Voice Production Readiness Checklist

Before moving an agent pipeline from local staging into production SIP/WebRTC routing, verify that every prompt and schema adheres to this operational checklist:

```
[ ] 1. All markdown characters (*, _, #, `, [ ]) are strictly banned via system instructions.
[ ] 2. Numeric values ($10.50, 4/12/2026, 1-800) have spoken translation rules enforced.
[ ] 3. VAD silence threshold is calibrated between 400ms and 600ms (avoids dead air vs. cutoffs).
[ ] 4. Tool functions implement conversational backchanneling (e.g., "Checking that now...").
[ ] 5. Maximum output token limits are capped between 80 and 150 tokens to guarantee short turns.
[ ] 6. Downstream speaker buffers flush immediately when `input_audio_buffer.speech_started` fires.
[ ] 7. Schema parameter descriptions explicitly explain formatting constraints to the LLM.
[ ] 8. Fallback rules exist for graceful error recovery if a tool times out (>1500ms).
