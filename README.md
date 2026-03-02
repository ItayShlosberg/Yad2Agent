# Yad2 WhatsApp Lead Agent

An AI-powered WhatsApp agent that screens inbound real-estate leads.  When a
potential buyer or renter messages about a listing, the agent answers property
questions, gradually qualifies the lead by collecting structured data, scores
them, and marks them as **qualified** or **disqualified** — all without human
intervention.

---

## Architecture

```
WhatsApp User
     │
     ▼
  Twilio (WhatsApp Sandbox / Business API)
     │  POST /webhook
     ▼
┌──────────────────────────────────────────┐
│  FastAPI  (src/api/webhook.py)           │
│    ↓                                     │
│  ConversationOrchestrator                │
│    ├── ConversationStore   (file I/O)    │
│    ├── LLMService          (OpenAI)      │
│    │     └── PromptBuilder (system prompt)│
│    │           └── ListingLoader (JSON)  │
│    ├── LeadScorer          (YAML rules)  │
│    └── ListingLoader       (media scan)  │
│                                          │
│  /media  (StaticFiles — images & videos) │
│  Models: Lead, Message                   │
│  Config: YAML + .env                     │
└──────────────────────────────────────────┘
     │  TwiML XML (+ <Media> URLs)
     ▼
  Twilio → WhatsApp User (text + images/videos)
```

### Message flow

1. Twilio receives a WhatsApp message and POSTs form data to `/webhook`.
2. The webhook hands the sender and body to the **ConversationOrchestrator**.
3. The orchestrator persists the inbound message, loads history + lead state.
4. **LLMService** makes two OpenAI calls:
   - *Reply call* (gpt-4o, plain text) — generates a natural response.
   - *Extraction call* (gpt-4o-mini, JSON mode) — pulls structured fields.
5. **LeadScorer** merges extracted fields into the Lead and recomputes the score.
6. If the reply contains a `[SEND_MEDIA]` marker, the orchestrator strips it
   and attaches all available property media URLs.
7. The orchestrator persists the outbound message and updated lead.
8. The webhook returns TwiML with `<Message>`, `<Body>`, and optional `<Media>` tags.

---

## Project Structure

```
Yad2Agent/
├── config/
│   ├── app.yaml              # Server, logging, paths, active property
│   ├── llm.yaml              # Model names, temperature, tokens
│   └── qualifying.yaml       # Fields to collect, scoring rules
├── src/
│   ├── main.py               # create_app() factory + uvicorn entry
│   ├── api/
│   │   └── webhook.py        # Thin route handlers (TwiML + media)
│   ├── core/
│   │   ├── config.py         # Typed config loaded from YAML + env
│   │   └── logging.py        # Centralised logging setup
│   ├── models/
│   │   ├── lead.py           # Lead, Intent, Criteria, Context, Signals
│   │   └── message.py        # Message model
│   └── services/
│       ├── llm_service.py    # OpenAI wrapper (reply + extraction)
│       ├── prompts.py        # System & extraction prompt builder
│       ├── store.py          # File-based conversation/lead persistence
│       ├── listing.py        # Listing JSON loader + media scanner
│       ├── scorer.py         # Config-driven scoring & field application
│       └── orchestrator.py   # Main workflow tying all services together
├── data/
│   ├── property_1/           # Each property gets its own folder
│   │   ├── listing.json      # Property details
│   │   └── media/            # Images and videos for this property
│   ├── property_2/
│   │   ├── listing.json
│   │   └── media/
│   │       ├── photo1.jpeg
│   │       └── tour.mp4
│   └── ...
├── storage/                  # Runtime data — scoped per property and phone
│   ├── property_1/
│   │   └── <phone>/
│   │       ├── conversation.json
│   │       └── lead.json
│   └── property_2/
│       └── ...
├── tests/
│   └── test_smoke.py         # Automated multi-turn smoke test
├── .env                      # Secrets (never committed)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Configuration

### `config/app.yaml` — Server & Paths

```yaml
server:
  host: "0.0.0.0"
  port: 8000
  reload: true            # set to false in production

logging:
  level: INFO
  format: "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"

paths:
  storage_dir: storage
  data_dir: data
  active_property: property_1   # switch this to serve a different property
```

### `config/llm.yaml` — LLM Settings

```yaml
reply:
  model: gpt-4o            # used for conversational replies
  temperature: 0.4
  max_tokens: 300

extraction:
  model: gpt-4o-mini       # used for structured field extraction
  temperature: 0.1
  max_tokens: 300

fallback_message: "תודה על ההודעה! אחזור אליך בהקדם."
```

### `config/qualifying.yaml` — What the Agent Asks About

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
  qualified_max_missing: 2    # lead qualifies with at most 2 fields missing
```

To add a new qualifying field: add an entry to `fields`, then make sure the
Lead model in `src/models/lead.py` has a corresponding attribute, and the
`missing_fields()` method has a checker for it.

### `.env` — Secrets

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
GPT=sk-xxxxxxxxxxxxxxxxxxxxxxxx
MEDIA_BASE_URL=https://your-ngrok-url.ngrok-free.dev
LOG_LEVEL=info
```

Secrets are **never** stored in YAML — only in `.env` (gitignored).
`MEDIA_BASE_URL` must be the publicly-reachable base URL (ngrok in dev, your
domain in prod) so Twilio can fetch media files.

---

## Local Development Setup

### Prerequisites

- Python 3.12+
- A Twilio account with WhatsApp Sandbox enabled
- An OpenAI API key
- ngrok (for exposing localhost to Twilio)

### Steps

```bash
# 1. Clone and enter the project
cd Yad2Agent

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
# source .venv/bin/activate          # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy .env.example to .env and fill in your keys
cp .env.example .env

# 5. Edit data/property_1/listing.json with your property details

# 6. Start the server
uvicorn src.main:app --reload --port 8000

# 7. In another terminal, expose via ngrok
ngrok http 8000

# 8. Configure Twilio WhatsApp Sandbox
#    Webhook URL:  https://<your-ngrok-url>/webhook
#    Method:       POST
```

### Quick Test

```bash
# Health check
curl http://localhost:8000/health

# Simulate a Twilio message
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=whatsapp%3A%2B972501234567&Body=Hello"
```

### Automated Smoke Test

With the server running:

```bash
python tests/test_smoke.py
```

Sends a 5-turn conversation and validates every response + final lead state.

---

## Conversation Flow

```
                    ┌───────────┐
                    │ Lead opens│
                    │   chat    │
                    └─────┬─────┘
                          ▼
                ┌───────────────────┐
                │ Answer property   │◄──── listing.json
                │ questions         │      (ground truth)
                └─────────┬─────────┘
                          ▼
                ┌───────────────────┐
                │ Ask ONE qualifying│◄──── qualifying.yaml
                │ question per turn │      (priority order)
                └─────────┬─────────┘
                          ▼
                ┌───────────────────┐
                │ Extract fields    │──── updates lead.json
                │ + score lead      │     (per-phone storage)
                └─────────┬─────────┘
                          ▼
                ┌───────────────────┐
          ┌─────│ Missing ≤ 2?      │─────┐
          │ no  └───────────────────┘ yes │
          ▼                               ▼
    Keep asking                    Mark "qualified"
                                   Offer next step
```

### Scoring

- Each filled required field: **+15 points**
- Wants to visit: **+10 bonus**
- Each red flag: **-15 penalty**
- Max score: **100**

### Status Transitions

| Status        | Trigger |
|---------------|---------|
| `collecting`  | Default — fields still being gathered |
| `qualified`   | Most fields collected, lead interested |
| `disqualified`| Lead not interested, budget way off, or disengaged |

---

## Lead Data Model

Stored as `storage/<property>/<phone>/lead.json`:

```json
{
  "phone": "whatsapp:+972501234567",
  "name": "דני",
  "status": "qualified",
  "intent": { "type": "buy" },
  "criteria": {
    "budget_max": 2400000,
    "budget_currency": "ILS",
    "equity_amount": 500000,
    "timeframe": "1-3 months",
    "wants_visit": true
  },
  "context": { "neighborhoods": [], "must_haves": [] },
  "signals": { "red_flags": [] },
  "score": 85
}
```

Passive fields like `has_mortgage_approval` are still stored if the lead
mentions them, but the agent won't actively ask about them.

---

## Multi-Property Listings

The system supports multiple property listings. Each property lives in its own
folder under `data/` with a `listing.json` and an optional `media/` subfolder.

### Adding a new property

1. Create a folder under `data/` (e.g. `data/property_3/`).
2. Add a `listing.json` with the property details.
3. Optionally add images and videos to `data/property_3/media/`.
4. Set `active_property: property_3` in `config/app.yaml`.
5. Restart the server.

### Switching the active property

Change `paths.active_property` in `config/app.yaml` and restart. The agent
will load the new property's listing and media. Conversation storage is scoped
per property, so each property maintains its own lead history.

### Media support

Place images (`.jpg`, `.jpeg`, `.png`, `.webp`) and videos (`.mp4`, `.mov`,
`.webm`) in the property's `media/` folder. When a lead asks to see photos or
the property, the agent automatically sends all available media via WhatsApp.

The `MEDIA_BASE_URL` environment variable must point to the public base URL
(your ngrok URL in development) so Twilio can fetch the files.

### Listing configuration

Edit `data/<property>/listing.json` with the property details. The agent uses
this as its **single source of truth** — it will never invent facts not in
this file.

Key sections: `property`, `pricing`, `availability`, `building_amenities`,
`location`, `highlights`, `known_issues`, `owner_instructions`.

The `owner_instructions` section controls agent behaviour:

```json
{
  "do_not_disclose": ["minimum_acceptable price"],
  "emphasize": ["forest view", "brand new"],
  "visit_policy": "coordinate directly with owner",
  "negotiation_policy": "do not negotiate — redirect to owner"
}
```

---

## Deployment Notes

For production:

1. Set `server.reload: false` in `config/app.yaml`.
2. Use a process manager (systemd, Docker, Fly.io, Render).
3. Replace the file-based store with a database (Postgres, SQLite, etc.) by
   implementing a new class with the same interface as `ConversationStore`.
4. Add webhook signature validation using `TWILIO_AUTH_TOKEN`.
5. Consider running behind a reverse proxy (nginx, Caddy) with HTTPS.

---

## Security & Privacy

- **PII**: Phone numbers are stored as folder names (digits only) under
  each property's storage directory.  In production, consider hashing them.
- **Secrets**: API keys live exclusively in `.env`, never in YAML or code.
- **Logging**: Hebrew message content appears in logs.  In production,
  reduce log level or redact PII from log output.
- **Retention**: Conversation and lead files persist indefinitely.
  Add a TTL / cleanup job for production.
