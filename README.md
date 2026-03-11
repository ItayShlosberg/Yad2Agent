# Yad2 WhatsApp Lead Agent

An AI-powered WhatsApp agent that screens inbound real-estate leads.  When a
potential buyer or renter messages about a listing, the agent answers property
questions, gradually qualifies the lead by collecting structured data, scores
them, and — once qualified — automatically notifies the property owner and
closes the conversation.

---

## Architecture

```
WhatsApp User
     │
     ▼
  Twilio (WhatsApp Sandbox / Business API)
     │  POST /webhook
     ▼
┌─────────────────────────────────────────────┐
│  FastAPI  (src/api/)                        │
│    ├── webhook.py       TwiML routes        │
│    ├── leads.py         GET /leads API      │
│    └── security.py      Twilio sig. check   │
│                                             │
│  ConversationOrchestrator                   │
│    ├── RateLimiter         (in-memory)      │
│    ├── ConversationStore   (file I/O)       │
│    ├── LLMService          (OpenAI)         │
│    │     └── PromptBuilder (system prompt)  │
│    │           └── ListingLoader (JSON)     │
│    ├── LeadScorer          (YAML rules)     │
│    ├── NotificationService (Twilio REST)    │
│    └── ListingLoader       (media scan)     │
│                                             │
│  /media  (StaticFiles — images & videos)    │
│  Models: Lead, Message, ExtractedFields     │
│  Config: YAML + .env                        │
└─────────────────────────────────────────────┘
     │  TwiML XML (+ <Media> URLs)
     ▼
  Twilio → WhatsApp User (text + images/videos)
```

### Message Flow

1. Twilio receives a WhatsApp message and POSTs form data to `/webhook`.
2. If Twilio signature validation is enabled, `security.py` verifies the `X-Twilio-Signature` header.
3. The webhook hands the sender and body to the **ConversationOrchestrator**.
4. The orchestrator checks end-state first:
   - **Closed** leads get a static reply — no LLM call.
   - **Disqualified** leads get a static reply — no LLM call.
5. The **RateLimiter** checks if the sender exceeded the message limit. If so, a cooldown reply is returned without calling the LLM.
6. **LLMService** makes two OpenAI calls:
   - *Reply call* (gpt-4o, plain text) — generates a natural response.
   - *Extraction call* (gpt-4o-mini, JSON schema mode) — pulls structured fields via Pydantic `ExtractedFields` model.
7. **LeadScorer** merges extracted fields into the Lead and recomputes the score.
8. If the lead just became **qualified** and hasn't been notified yet:
   - **NotificationService** sends a WhatsApp summary to the property owner.
   - The lead is marked **closed** with `notified_at` and `closed_at` timestamps.
9. If the reply contains a `[SEND_MEDIA]` marker, the orchestrator strips it and attaches all available property media URLs.
10. The webhook returns TwiML with `<Message>`, `<Body>`, and optional `<Media>` tags.

---

## Project Structure

```
Yad2Agent/
├── config/
│   ├── app.yaml              # Server, logging, paths, notification, rate limit, security
│   ├── llm.yaml              # Model names, temperature, tokens
│   └── qualifying.yaml       # Fields to collect, scoring rules
├── src/
│   ├── main.py               # create_app() factory + uvicorn entry
│   ├── api/
│   │   ├── webhook.py        # Thin route handlers (TwiML + media)
│   │   ├── leads.py          # GET /leads summary endpoint
│   │   └── security.py       # Twilio signature validation dependency
│   ├── core/
│   │   ├── config.py         # Typed config loaded from YAML + env
│   │   └── logging.py        # Centralised logging setup
│   ├── models/
│   │   ├── lead.py           # Lead, Intent, Criteria, Context, Signals
│   │   ├── message.py        # Message model
│   │   └── extraction.py     # Pydantic ExtractedFields for LLM output
│   └── services/
│       ├── llm_service.py    # OpenAI wrapper (reply + structured extraction)
│       ├── prompts.py        # System & extraction prompt builder
│       ├── store.py          # File-based conversation/lead persistence
│       ├── listing.py        # Listing JSON loader + media scanner
│       ├── scorer.py         # Config-driven scoring & field application
│       ├── orchestrator.py   # Main workflow tying all services together
│       ├── notifier.py       # Owner WhatsApp notification via Twilio REST
│       └── rate_limiter.py   # In-memory sliding-window rate limiter
├── data/
│   ├── property_1/           # Each property gets its own folder
│   │   ├── listing.json
│   │   └── media/
│   ├── property_2/
│   │   ├── listing.json
│   │   └── media/
│   └── ...
├── storage/                  # Runtime data — scoped per property and phone
│   ├── property_1/
│   │   └── <phone>/
│   │       ├── conversation.json
│   │       └── lead.json
│   └── property_2/ ...
├── tests/
│   ├── test_smoke.py         # Automated multi-turn smoke test
│   ├── test_end_state.py     # Conversation end-state + notification tests
│   ├── test_rate_limiter.py  # Rate limiter unit tests
│   ├── test_extraction.py    # Pydantic extraction model tests
│   ├── test_leads_api.py     # Leads endpoint integration tests
│   └── test_security.py      # Twilio signature validation tests
├── .env                      # Secrets (never committed)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Configuration

### `config/app.yaml` — Server, Paths & Features

```yaml
server:
  host: "0.0.0.0"
  port: 8000
  reload: true

logging:
  level: INFO
  file_enabled: true
  file_path: logs/agent.log
  json_enabled: true
  json_path: logs/agent.jsonl

paths:
  storage_dir: storage
  data_dir: data
  active_property: property_1

notification:
  enabled: true               # send WhatsApp summary to owner on qualification

rate_limit:
  max_messages: 10
  window_seconds: 300          # 10 messages per 5 minutes per phone
  cooldown_message: "אתה שולח הודעות מהר מדי. נסה שוב בעוד מספר דקות."

security:
  validate_twilio_signature: false   # set true in production
```

### `config/llm.yaml` — LLM Settings

```yaml
reply:
  model: gpt-4o
  temperature: 0.4
  max_tokens: 300

extraction:
  model: gpt-4o-mini
  temperature: 0.1
  max_tokens: 300

fallback_message: "תודה על ההודעה! אחזור אליך בהקדם."
```

### `config/qualifying.yaml` — What the Agent Collects

```yaml
fields:
  - name: intent
    description: "buy or rent"
    required: true
    priority: 1
  - name: budget_range
    description: "budget_min / budget_max in ILS"
    required: true
    priority: 2
  - name: timeframe
    description: "urgency / timeframe"
    required: true
    priority: 3
  - name: wants_visit
    description: "interest in visiting the property"
    required: true
    priority: 4
  - name: equity_amount
    description: "cash / equity available"
    required: true
    priority: 5

scoring:
  points_per_field: 15
  visit_bonus: 10
  red_flag_penalty: 15
  max_score: 100

status_transitions:
  qualified_max_missing: 2
```

### `.env` — Secrets

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
OWNER_WHATSAPP_NUMBER=whatsapp:+972546487753
GPT=sk-xxxxxxxxxxxxxxxxxxxxxxxx
MEDIA_BASE_URL=https://your-ngrok-url.ngrok-free.dev
```

Secrets are **never** stored in YAML — only in `.env` (gitignored).

---

## Features

### Owner Notification

When a lead qualifies (enough fields collected, lead interested), the system:
1. Sends a structured WhatsApp summary to `OWNER_WHATSAPP_NUMBER` via Twilio REST API.
2. Sets `lead.notified_at` to prevent duplicate notifications.
3. Transitions the lead to `closed` status.
4. Appends a handoff message to the WhatsApp reply.

Toggle with `notification.enabled` in `app.yaml`. Requires the `twilio` package.

### Conversation End State

Leads have four statuses: `collecting`, `qualified`, `disqualified`, `closed`.

| Status         | Behavior |
|----------------|----------|
| `collecting`   | Normal LLM conversation — fields being gathered |
| `qualified`    | Triggers notification + auto-transition to `closed` |
| `disqualified` | Static reply — no LLM call, no OpenAI cost |
| `closed`       | Static reply — no LLM call, no OpenAI cost |

Once a lead is `closed` or `disqualified`, further messages get a polite static response without any LLM invocation.

### Leads Summary API

```
GET /leads                     # all leads, sorted by last activity
GET /leads?status=qualified    # filter by status
GET /leads?property=property_2 # filter by property
```

Returns a JSON array with phone, name, status, score, intent, budget, message count, timestamps, and notification info.

### Rate Limiting

An in-memory sliding-window rate limiter protects against message floods:
- Default: 10 messages per 5 minutes per phone number.
- Exceeding the limit returns a cooldown message without calling OpenAI.
- Configured in `app.yaml` under `rate_limit`.

### Pydantic Structured Extraction

The LLM extraction call uses OpenAI's `response_format` with a JSON schema derived from the `ExtractedFields` Pydantic model. This provides:
- Type-safe field extraction (Literal types for intent/status, Optional for all fields).
- Automatic validation — malformed LLM output is caught and logged.
- Clean integration with the scorer via `model_dump(exclude_none=True)`.

### Twilio Signature Validation

When `security.validate_twilio_signature: true`, incoming webhook requests are verified using the `X-Twilio-Signature` header and `TWILIO_AUTH_TOKEN`. Invalid or missing signatures return HTTP 403. Disabled by default for local development.

### Multi-Property Listings

Each property lives in its own folder under `data/` with a `listing.json` and optional `media/` subfolder. Switch properties by changing `paths.active_property` in `app.yaml`. Conversations are scoped per property.

### Media Support

Images (`.jpg`, `.jpeg`, `.png`, `.webp`) and videos (`.mp4`, `.mov`, `.webm`) in the `media/` folder are automatically sent when the lead asks for photos. One media file per WhatsApp message (WhatsApp protocol limit), sent as separate `<Message>` elements in TwiML.

---

## Local Development Setup

### Prerequisites

- Python 3.12+
- A Twilio account with WhatsApp Sandbox enabled
- An OpenAI API key
- ngrok (for exposing localhost to Twilio)

### Steps

```bash
cd Yad2Agent
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
# source .venv/bin/activate          # macOS / Linux

pip install -r requirements.txt

cp .env.example .env                 # fill in your keys

uvicorn src.main:app --reload --reload-include "*.yaml" --port 8000

# In another terminal:
ngrok http 8000
```

Configure the Twilio WhatsApp Sandbox webhook URL to `https://<ngrok-url>/webhook` (POST).

### Quick Test

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=whatsapp%3A%2B972501234567&Body=Hello"

curl http://localhost:8000/leads
```

### Running Tests

```bash
python -m pytest tests/ -v
```

---

## Conversation Flow

```
                    ┌───────────┐
                    │ Lead opens│
                    │   chat    │
                    └─────┬─────┘
                          ▼
                ┌───────────────────┐
                │ Rate limit check  │──── over limit? → cooldown reply
                └─────────┬─────────┘
                          ▼
                ┌───────────────────┐
                │ End-state check   │──── closed/disqualified? → static reply
                └─────────┬─────────┘
                          ▼
                ┌───────────────────┐
                │ Answer property   │◄──── listing.json
                │ questions         │
                └─────────┬─────────┘
                          ▼
                ┌───────────────────┐
                │ Ask ONE qualifying│◄──── qualifying.yaml
                │ question per turn │
                └─────────┬─────────┘
                          ▼
                ┌───────────────────┐
                │ Extract fields    │──── Pydantic ExtractedFields
                │ + score lead      │     + updates lead.json
                └─────────┬─────────┘
                          ▼
                ┌───────────────────┐
          ┌─────│ Qualified?        │─────┐
          │ no  └───────────────────┘ yes │
          ▼                               ▼
    Keep asking                    Notify owner (WhatsApp)
                                   Set status = closed
                                   Append handoff message
```

### Scoring

- Each filled required field: **+15 points**
- Wants to visit: **+10 bonus**
- Each red flag: **-15 penalty**
- Max score: **100**

### Lead Data Model

Stored as `storage/<property>/<phone>/lead.json`:

```json
{
  "phone": "whatsapp:+972501234567",
  "name": "דני",
  "status": "closed",
  "intent": { "type": "buy" },
  "criteria": {
    "budget_max": 2400000,
    "timeframe": "1-3 months",
    "wants_visit": true
  },
  "signals": { "red_flags": [] },
  "score": 85,
  "notified_at": "2026-03-01T10:00:00+00:00",
  "closed_at": "2026-03-01T10:00:00+00:00"
}
```

---

## Deployment Notes

For production:

1. Set `server.reload: false` in `config/app.yaml`.
2. Set `security.validate_twilio_signature: true`.
3. Use a process manager (systemd, Docker, Fly.io, Render).
4. Replace the file-based store with a database by implementing a new class with the same `ConversationStore` interface.
5. Run behind a reverse proxy (nginx, Caddy) with HTTPS.
6. Set `MEDIA_BASE_URL` to your production domain.

---

## Security & Privacy

- **Signature validation**: Enable `security.validate_twilio_signature` in production to reject forged webhook requests.
- **Rate limiting**: Prevents message floods and OpenAI cost abuse (configurable per-phone limits).
- **PII**: Phone numbers are stored as folder names (digits only). In production, consider hashing.
- **Secrets**: API keys live exclusively in `.env`, never in YAML or code.
- **Logging**: Hebrew message content appears in logs. In production, reduce log level or redact PII.
- **Retention**: Conversation and lead files persist indefinitely. Add a TTL / cleanup job for production.
- **End state**: Closed/disqualified leads incur zero OpenAI cost on subsequent messages.
