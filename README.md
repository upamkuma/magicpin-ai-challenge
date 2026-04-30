# Vera Bot — magicpin AI Challenge Submission

**Team**: Team Upam  
**Contact**: upam@example.com  
**Model**: Rule-based composer v1

---

## Quick Start

```bash
# Install
pip3 install -r requirements.txt

# Start bot
python3 -m uvicorn bot:app --host 0.0.0.0 --port 8080

# Load dataset
python3 load_dataset.py

# Regenerate submission.jsonl
python3 generate_submission.py

# Run judge (requires LLM_API_KEY in judge_simulator.py)
python3 judge_simulator.py
```

Or use the one-command startup:
```bash
bash run.sh
```

---

## Architecture

```
┌────────────────────────────────────────────────┐
│                   Bot Server                    │
│                  (FastAPI)                       │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ /healthz │  │/metadata │  │  /context     │  │
│  └──────────┘  └──────────┘  │ (push store)  │  │
│                               └──────────────┘  │
│  ┌──────────────┐  ┌───────────────────────┐    │
│  │   /tick       │  │      /reply           │    │
│  │ (compose)     │  │ (multi-turn handler)  │    │
│  └──────┬───────┘  └───────────┬───────────┘    │
│         │                      │                 │
│  ┌──────▼──────────────────────▼───────────┐    │
│  │     Quality Gate (pre-send validation)   │    │
│  │  5-dimension scoring · hard rejections   │    │
│  └──────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────┐    │
│  │        Context Store (in-memory)         │    │
│  │  categories · merchants · customers      │    │
│  │  triggers · conversations · suppression  │    │
│  └──────────────────────────────────────────┘    │
└────────────────────────────────────────────────┘
```

### 5 API Endpoints

| Endpoint | Method | Purpose | Latency |
|---|---|---|---|
| `/v1/healthz` | GET | Liveness + context counts | <10ms |
| `/v1/metadata` | GET | Team identity | <10ms |
| `/v1/context` | POST | Idempotent context push with version conflict | <10ms |
| `/v1/tick` | POST | Compose messages from trigger batch | <50ms |
| `/v1/reply` | POST | Multi-turn conversation handling | <10ms |

---

## Composition Strategy

The `compose_message()` function implements a **trigger-kind dispatch** pattern:

1. **Resolves all 4 contexts**: Category → Merchant → Trigger → Customer
2. **Enriches placeholder triggers** with sensible defaults from merchant/category data
3. **Selects handler** by `trigger.kind` (24 handlers)
4. **Extracts relevant data**: owner name, active offers, signals, performance, review themes
5. **Composes message** matching category voice profile + merchant-specific data
6. **Quality gate validation**: 5-dimension scoring (relevance, timing, personalization, clarity, trust)
7. **Sets appropriate CTA**: `open_ended`, `binary_yes_no`, `multi_choice_slot`, etc.
8. **Applies suppression**: Prevents duplicate sends via `suppression_key`

### Quality Gate

Every outbound message passes through `quality_gate.py` before delivery:

- **Hard rejection rules**: empty body, filler phrases, scarcity language, promotional spam, URLs, duplicate messages, category-restricted vocabulary
- **5-dimension scoring** (relevance 0-3, timing 0-2, personalization 0-2, clarity 0-2, trust 0-1): messages scoring below 5/10 are blocked
- **Category tone validation**: e.g., sales language blocked in clinical contexts

### Supported Trigger Kinds (24)

| Kind | Scope | Description |
|---|---|---|
| `research_digest` | merchant | New research relevant to category |
| `regulation_change` | merchant | Compliance deadline alerts |
| `recall_due` | customer | Service recall reminders |
| `perf_dip` | merchant | Performance decline alerts |
| `perf_spike` | merchant | Performance uptick acknowledgment |
| `renewal_due` | merchant | Subscription renewal nudge |
| `festival_upcoming` | merchant | Festive campaign planning |
| `wedding_package_followup` | customer | Bridal timeline management |
| `curious_ask_due` | merchant | Engagement cadence questions |
| `winback_eligible` | merchant | Expired subscription re-engagement |
| `ipl_match_today` | merchant | Real-time event-driven promotions |
| `review_theme_emerged` | merchant | Review pattern alerts |
| `milestone_reached` | merchant | Social proof opportunities |
| `active_planning_intent` | merchant | Planning continuation |
| `seasonal_perf_dip` | merchant | Seasonal dip reframing |
| `customer_lapsed_hard` | customer | Hard-lapsed winback |
| `customer_lapsed_soft` | customer | Soft-lapsed re-engagement |
| `supply_alert` | merchant | Drug recall / compliance |
| `chronic_refill_due` | customer | Medication refill reminders |
| `category_seasonal` | merchant | Seasonal demand shift alerts |
| `gbp_unverified` | merchant | GBP verification nudge |
| `cde_opportunity` | merchant | CDE/webinar invitations |
| `competitor_opened` | merchant | Competitive positioning |
| `dormant_with_vera` | merchant | Re-engagement after silence |
| `trial_followup` | customer | Post-trial conversion |
| `appointment_tomorrow` | customer | Appointment reminders |

---

## Multi-Turn Handling

The `/v1/reply` endpoint (+ `conversation_handlers.py`) implements:

- **Auto-reply detection**: Detects canned WhatsApp Business replies  
  Turn 1 → gentle nudge · Turn 2 → wait 24h · Turn 3 → end conversation
- **Intent transition**: Detects "yes"/"let's do it" → switches to action mode immediately
- **Hostile handling**: Detects "stop messaging" → graceful exit with opt-back-in
- **Off-topic routing**: Detects GST/tax/legal → politely declines, redirects to thread

---

## Files

| File | Purpose |
|---|---|
| `bot.py` | Main bot server with all 5 endpoints + composer |
| `quality_gate.py` | Pre-send validation with 5-dimension scoring |
| `conversation_handlers.py` | Multi-turn state machine (standalone reference) |
| `generate_submission.py` | Automated submission.jsonl generator |
| `load_dataset.py` | Dataset loader utility |
| `judge_simulator.py` | LLM-powered judge for self-testing |
| `submission.jsonl` | 30 test pair compositions |
| `requirements.txt` | Python dependencies |

---

## Tradeoffs & Design Decisions

1. **Rule-based vs LLM**: Chose deterministic rules for reliability, speed (<50ms), and zero hallucination risk. Trade-off: less creative copy.
2. **Placeholder handling**: Many expanded-dataset triggers have `placeholder: true` with no real payload. The bot synthesizes sensible defaults from merchant/category data (e.g., deriving perf metrics from `delta_7d`, computing milestones from current views).
3. **Quality gate at 5/10**: Balanced threshold that blocks genuinely bad messages (spam, filler, restricted vocabulary) without suppressing context-grounded messages with low urgency.
4. **In-memory store**: Simple dict-based storage. Resets on restart. Production would use Redis/SQLite.
5. **Suppression**: Global suppression set prevents duplicate sends per trigger key.
6. **Language mixing**: Hindi-English code-mix for `hi` language preferences using conditional string construction.
7. **Festival handling**: Far-out festivals (>30d) get a "set a reminder" message instead of being suppressed.

## What Would Help Most

- Real merchant conversation logs for tone calibration
- A/B test data on which CTA shapes drive highest reply rates  
- Customer visit history depth for richer recall/lapse messages
- LLM integration for dynamic copy generation in edge cases
