# PROJECT_STATE.md — Swaram

> Source of truth for every coding agent. **Read it fully before coding. Update it before you finish.**
> Last updated: 2026-10-09 · Status: Core implemented; external supervisor implemented for review · Version: 9

---

## 0. Rules for coding agents

1. Keep it simple. If a task seems to need a new service, queue, or framework, stop and use the existing parts. Anything in §3 "Parked" stays parked.
2. Contracts in §7 are law. Change §7 first, log it in §16, then code.
3. Mock-first: ElevenLabs, telephony and the LLM sit behind small adapters with a mock. Everything runs with `PROVIDER_MODE=mock`.
4. No PII, keys or recordings in code, logs or git. Mask phones in logs and UI by default.
5. Minimal code, no explanatory comments. Typed (mypy / TS strict).
6. ElevenLabs names in this file are from docs search and memory, marked **(verify)**. Check `https://elevenlabs.io/docs/llms.txt` (append `.md` to any docs URL) before coding against them.
7. Stay in your owned directories (§12). Update §13 (tasks) and §16 (changelog) in the same PR.
8. Do not edit `README.md` in future work. Treat it as user-owned; put project setup and implementation guidance in this file or other appropriate docs unless the user explicitly asks to change the README.

Status legend: `todo` · `wip` · `blocked` · `review` · `done`

---

## 1. Snapshot

| | |
|---|---|
| Project | **Swaram** (Malayalam: voice) · repo `swaram` |
| One line | Upload contacts, pick a template, calls go out in each person's language, replies are understood, dashboard shows who confirmed, one click retries the rest |
| Event / track | DEFINE 4.0 · PR 002 (Software) |
| Voice | **ElevenLabs** Agents (speech, LLM turn-taking, TTS) over a Twilio or Exotel number |
| Pitch | "One platform, any template, any language, with privacy built in." |

---

## 2. Product flow (4 steps)

1. **Create campaign.** Upload CSV (`name, phone, language, segment?`) and fill a template, e.g. "Workshop on {topic} at {venue} on {date}."
2. **AI writes scripts.** One LLM call turns the template into a natural script per language (ml, hi, en; ta stretch). Operator previews/edits and approves.
3. **Platform calls.** Per person: greet → message → ask → capture answer → confirm → end. Person can **speak or press a key** (1 yes, 2 no).
   - Voicemail → leave short message, mark `voicemail` (retryable).
   - No answer → mark `no_answer` (retryable).
4. **Dashboard.** Confirmed / declined / no answer / voicemail by language and segment. **Retry non-responders** button calls them again.

Reminders and updates reuse the same machinery: **Follow-up** button creates a new campaign from the old one with an audience filter (confirmed / non-responders / all) and a new template ("reminder", "venue changed"). No lifecycle engine.

```mermaid
flowchart TD
    A[Create campaign: list + template] --> B[AI scripts per language]
    B --> C[Call flow: voice or keypad]
    C --> E[Replied: AI reads reply]
    C --> F[Voicemail: short message]
    C --> G[No answer: mark for retry]
    E --> H[Dashboard: outcomes by language]
    F --> H
    G --> H
    H --> I[Retry non-responders]
    I -.-> C
```

### What is AI vs plain code

| Part | How |
|---|---|
| Script per language | Optional open-weight model through Hugging Face Inference Providers; reviewed by organizer |
| Understanding spoken replies | AI (ElevenLabs agent: STT + LLM) |
| Call flow, retries, grouping, consent, call hours, privacy | Plain code |

---

## 3. Scope

**Phase 1 (showable demo):** campaign creation + CSV import · mock script generation with preview/approve · simulated outcomes in en/hi/ml · dashboard by language/segment with retry · two templates (workshop invite, clinic reminder) · privacy basics (§11) · mock mode + simulator. No outbound calls are placed.

**Phase 2 (live calling):** ElevenLabs calls in en/hi/ml · speech reply and keypad verification · voicemail/no-answer reconciliation · per-language accuracy and latency numbers. Requires provider configuration and consented test numbers.

**External supervision (approved):** A separate supervisor service observes privacy-minimized campaign snapshots, analyzes outcomes by language and segment, recommends bounded retries, and opens a human review queue for uncertain or exhausted cases. It does not join calls or directly edit scripts/outcomes. Automatic retries are opt-in and remain subject to Swaram's call window, opt-out, consent, and `MAX_ATTEMPTS` rules. Script approval stays with a human in the core dashboard.

**Stretch (in order):** Follow-up campaign (reminder/update to confirmed) · call detail drawer with transcript and outcome ("agent trace") · payment-reminder template · Tamil · cost/minutes per campaign · browser "call me" fallback · WhatsApp fallback.

**Parked (do NOT build unless the lead moves it up):** Temporal/workflow engine · Redis · MinIO · pgvector/semantic search · RLS/multi-tenant · Presidio · bandit/smart retry timing · waitlist promotion · event versioning/diffing · CRM connectors · live takeover/monitoring · contact memory · self-hosted STT/TTS · LiveKit.

---

## 4. Architecture and stack

```
Organizer ──> Next.js dashboard ──REST──> Swaram API ──> Swaram SQLite
                    │                         │
                    │                         └── asyncio dialer ──> VoiceProvider
                    │                                                   │
                    │                                  ElevenLabs Agent ──> phone
                    │                                  record_outcome + webhook
                    │
                    └──REST──> External Supervisor API ──> Supervisor SQLite
                                    │
                                    ├── GET minimized snapshot (Bearer token) ──> Swaram API
                                    └── POST bounded retry (opt-in token) ──────> Swaram API
```

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, httpx, tenacity |
| External supervisor | Separate FastAPI process, read-only snapshot client, independent SQLite review store |
| DB | SQLite file (single container). Swap to Postgres only if concurrency demands |
| Jobs | One asyncio dialer loop + semaphore. No external queue |
| Live updates | Dashboard polls every 3 s |
| Frontend | Next.js 15, TypeScript, Tailwind, shadcn/ui, TanStack Query, Recharts |
| Voice | ElevenLabs Agents + Scribe STT + TTS (`eleven_flash_v2_5` default; `eleven_v3` where a language needs it, likely Malayalam **(verify)**) |
| LLM | Optional Hugging Face Inference Providers chat API for draft scripts and aggregate supervisor insights; configured with a fine-grained inference token and model ID |
| Privacy | `cryptography` Fernet for name/phone, HMAC phone hash, regex redaction |
| Dev/CI | uv, ruff, mypy, pytest, pnpm, Docker Compose (api + web + supervisor), GitHub Actions |

Language notes **(verify in T-04 bake-off)**: Scribe v2 Realtime lists Hindi, Tamil, Malayalam among 90+ languages; Flash v2.5 lists Hindi and Tamil; Malayalam appears in the Eleven v3 list.

---

## 5. Repo layout

```
swaram/
├── PROJECT_STATE.md  docker-compose.yml  .env.example  .github/workflows/ci.yml
├── apps/
│   ├── api/{Dockerfile,pyproject.toml} app/{main.py,seed_demo.py} app/providers/{base.py,mock.py} tests/
│   │        /routers/{campaigns,templates,summary,webhooks,tools}.py
│   │        /services/{scripts,dialer,outcomes,privacy,csv_import}.py
│   │        /providers/{base.py,elevenlabs.py,mock.py}
│   ├── supervisor/{Dockerfile,pyproject.toml} app/{main.py,analysis.py,store.py}
│   └── web/{Dockerfile,package.json} app/{campaigns/,supervisor/,components/,lib/,layout.tsx,globals.css}
├── templates/            # future provider prompt and template files
├── evals/                # lang_eval.py, golden utterances
├── scripts/              # seed_demo.py, simulate.py
└── docs/                 # data-flow.md, demo-runbook.md
```

---

## 6. Data model (SQLite)

| Table | Columns |
|---|---|
| `campaigns` | id, name, template_id, fields(json), languages(json), status(draft/ready/running/done), parent_id?, created_at |
| `scripts` | campaign_id, language, first_message, voicemail_message, key_points, approved |
| `contacts` | id, campaign_id, name_enc, phone_enc, phone_hash, language, segment, opted_out |
| `calls` | id, contact_id, campaign_id, attempt_no, state, outcome, conversation_id, input_mode(speech/keypad), duration_s, transcript_redacted, recording_expires_at, started_at, ended_at |
| `demo_rsvp_calls` | id, batch_id, scenario, normalized outcome from ElevenLabs `record_outcome`, exact simulated participant response, redacted transcript, provider, test/invocation IDs, extraction status, created_at |
| `demo_rsvp_runs` | id, status, ElevenLabs invocation ID, error, created_at, finished_at |
| `demo_rsvp_tests` | scenario, organizer agent ID, reusable ElevenLabs simulation test ID |

`calls.state`: `queued → dialing → done | failed`
`calls.outcome`: `confirmed | declined | maybe | callback | optout | no_answer | voicemail | failed`
Non-responders = latest outcome in `{no_answer, voicemail, failed}`. Max attempts per contact: 3 (`MAX_ATTEMPTS`).

---

## 7. Contracts (v1) — change here first

### 7.1 REST

| Endpoint | Purpose |
|---|---|
| `GET /templates` | list templates (id, name, fields, allowed outcomes) |
| `POST /campaigns` (multipart: csv, template_id, fields, languages) | validate template fields and contacts, create language scripts, status `draft` |
| `GET /campaigns`, `GET /campaigns/{id}` | list / detail with scripts |
| `PATCH /campaigns/{id}/scripts/{lang}` | edit script text |
| `POST /campaigns/{id}/approve` | draft only: approve all scripts → `ready` |
| `POST /campaigns/{id}/launch` | ready only: queue first attempt per contact → `running` |
| `POST /campaigns/{id}/retry` | completed campaign only: queue eligible latest non-responder attempts (respects `MAX_ATTEMPTS`) |
| `POST /campaigns/{id}/followup` `{template_id, fields, audience}` | new campaign cloned from contacts matching `confirmed|declined|non_responders|all` (stretch) |
| `GET /campaigns/{id}/summary` | counts by outcome × language and segment, totals, and eligible retryable-contact count |
| `GET /campaigns/{id}/calls` | masked list (name initial + `+91•••••1234`, outcome, language, attempt) |
| `POST /demo/rsvp/runs` | start three ElevenLabs Agent Testing simulations with Yes, No, and unsure simulated-user personas; never dials a number |
| `GET /demo/rsvp/runs/{run_id}` | poll run status and retrieve the resulting ElevenLabs transcript/outcome records |
| `GET /demo/rsvp/calls` | list persisted ElevenLabs RSVP simulations with exact participant replies and tool-extracted outcomes |
| `GET /demo/rsvp/calls.csv` | export persisted ElevenLabs RSVP simulations as CSV |
| `GET /calls/{id}` | redacted transcript + outcome + input mode (stretch drawer) |
| `DELETE /campaigns/{id}` | erase contacts, calls, transcripts, recordings |
| `GET /supervision/snapshot` | token-protected, minimized campaign/scripts/call status snapshot for the separate supervisor; no names, phones, or transcripts |
| `POST /supervision/campaigns/{id}/retry` | token-protected bounded retry request from supervisor; available only when `SUPERVISOR_AUTO_RETRY=true` |
| `PATCH /calls/{id}/outcome` | human corrects a completed call outcome from the campaign review view; opt-out cannot be reversed |

### 7.2 Voice provider

```python
class VoiceProvider(Protocol):
    async def start_call(self, call: CallRequest) -> str: ...
    async def get_conversation(self, conversation_id: str) -> ConversationRecord: ...
    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> bool: ...

class CallRequest(BaseModel):
    call_id: UUID
    to_e164: str
    language: str
    first_message: str
    voicemail_message: str
    key_points: str
    dynamic_variables: dict[str, str]
```

`MockProvider` fakes the whole call: waits 1–4 s, picks an outcome by weighted random per language, then invokes the same internal handlers as the real tool/webhook. Used by `scripts/simulate.py` to fill the dashboard.

### 7.3 ElevenLabs integration **(verify each)**

| Need | Mechanism |
|---|---|
| Place call | Native outbound endpoint selected by `TELEPHONY_KIND`: Twilio (`/v1/convai/twilio/outbound-call`) or Exotel (`/v1/convai/exotel/outbound-call`) |
| Per-call content | `conversation_initiation_client_data`: `dynamic_variables` + `conversation_config_override` (first_message, language, prompt). Enable overrides in the agent's security settings |
| Capture answer | Server (webhook) tool `record_outcome` |
| Voicemail | Voicemail-detection system tool if available, else prompt rule + end-call tool |
| Keypad | Check whether the agent accepts incoming DTMF on the chosen number type. If not, see risk R2 |
| After call | Post-call webhook (HMAC-verified): transcript, duration, analysis |

One agent total (`swaram-agent`), created by `scripts/` helper or the dashboard, configured per call via overrides. No agent factory.

### 7.4 Tool `record_outcome` (agent → API)

`POST /voice/tools/record_outcome` (header `X-Tool-Secret`)

```json
{"call_id":"uuid","outcome":"confirmed|declined|maybe|callback|optout","input_mode":"speech|keypad","party_size":null,"callback_time":null}
```

Idempotent per `call_id`. `optout` sets `contacts.opted_out`. Response `{ "ok": true }`.

### 7.5 Webhook `POST /webhooks/elevenlabs`

Verify signature and accept `post_call_transcription` and `call_initiation_failure`. Map `conversation_id` to `call`; initiation failures become retryable `no_answer` or `failed` outcomes. For post-call transcription, preserve an outcome already captured by `record_outcome`; otherwise map no-answer/voicemail from the provider result or use retryable `failed`. Redact and store transcript, duration, and end time. Dedupe repeated deliveries by conversation and event type.

### 7.7 External supervisor

The separate supervisor service polls `GET /supervision/snapshot` with a shared bearer token. The snapshot includes campaign/script approval states and per-call opaque IDs, attempt, state, outcome, language, segment, opt-out flag, and duration; it excludes contact names, phone numbers, and transcripts. The supervisor stores snapshots and review items in its own database and has no Swaram database access.

The supervisor opens a human review item immediately for completed `maybe`/`callback` outcomes and when a contact remains unresolved (`no_answer`, `voicemail`, or `failed`) at `MAX_ATTEMPTS`. A reviewer can open the exact campaign call, inspect its redacted transcript, and correct the outcome in Swaram; opt-out cannot be reversed. It recommends retries for eligible non-responders. Automatic retry is disabled by default; when explicitly enabled, it can only call the bounded Swaram retry endpoint, which rechecks eligibility and relies on the existing queue for call hours and opt-outs. Optional LLM analysis receives aggregate metrics only; deterministic rules own review classification and retry eligibility.

### 7.6 Template file (`templates/<id>.yaml`)

```yaml
id: workshop_invite
name: Workshop invitation
fields: [topic, venue, date, time, organiser]
question: "Will you attend?"
outcomes: [confirmed, declined, maybe, callback, optout]
keypad: {"1": confirmed, "2": declined}
base_message: "Workshop on {topic} at {venue} on {date} at {time}, organised by {organiser}."
```

Ship `workshop_invite` and `clinic_reminder` (outcomes: confirmed, reschedule→callback, optout). Stretch: `workshop_reminder`, `payment_reminder` (calm tone, state amount and due date once, no pressure).

---

## 8. Voice and dialer

### 8.1 Dialer loop (`services/dialer.py`)
The queue polls every 2 s while a campaign has queued or dialing calls and resumes campaigns marked `running` after API startup. For live calls, it only starts queued calls inside `CALL_WINDOW` (default 09:00–20:00 IST), skips `opted_out`, and limits total active calls to `MAX_CONCURRENT`; simulated calls bypass the time window. Calls stuck in `dialing` longer than `CALL_TIMEOUT_S` are reconciled via `get_conversation`; active provider calls remain dialing, terminal results are saved, and unknown/error results become retryable `failed` outcomes. A failed outbound-call request is marked failed for explicit review/retry rather than blindly repeating a request that might already have connected the call.

### 8.2 Why this voice design (pitch)
Scripted facts (date, venue, time) are injected verbatim from the approved script; the agent LLM only interprets replies and answers simple questions from `key_points`. Cheap, no hallucinated details, still conversational. Speech and keypad both accepted; voicemail and no-answer are explicit outcomes and retryable.

### 8.3 Languages
| Lang | Status |
|---|---|
| en, hi | baseline |
| ml | bake-off required (T-04) |
| ta | stretch |

### 8.4 Fallbacks
No phone line at demo → `MockProvider` for dashboards + one pre-recorded real call + browser provider if built. ElevenLabs outage → mock mode toggle (`PROVIDER_MODE=mock`).

---

## 9. AI pieces

### 9.1 Script generator (`services/scripts.py`)
Input: template + filled fields + one language. Output is schema-validated:
`{"first_message": "...", "voicemail_message": "...", "key_points": "..."}`.
`SCRIPT_PROVIDER_MODE=mock` is the default and uses the local mock generator. `SCRIPT_PROVIDER_MODE=huggingface` uses `HF_TOKEN` and `HF_MODEL` through the Hugging Face Inference Providers chat-completion router (default model: `Qwen/Qwen3.8-27B:fastest`). Send only template text, language, and campaign field values; never contact data. Require valid JSON, concise polite copy, no invented facts, and approved source facts in the key points. A human reviews the draft before approval.

### 9.2 Voice agent prompt (`templates/agent_prompt.md`)

```
You are calling {{contact_name}} on behalf of {{organiser}}.
Start in {{language}}; switch if the person answers in another supported language.
Say the first message exactly. Then ask the question and wait.
Accept spoken answers or keypad (1 yes, 2 no). Confirm the answer in one short sentence.
Call record_outcome once with confirmed|declined|maybe|callback|optout, then end the call.
Answer simple questions only from KEY_POINTS: {{key_points}}. Otherwise say the organiser will follow up and record callback.
If voicemail is detected, say {{voicemail_message}} and end the call.
If they ask not to be called, apologise, record optout, end.
Never invent details, never pressure, never read out numbers or IDs.
```

### 9.3 Accuracy numbers (required for demo)
`evals/lang_eval.py`: 10–15 spoken test phrases per language (yes, no, maybe, "call me later", code-mixed examples) played through the agent path or Scribe; report intent accuracy per language and note latency. Put the table on the pitch slide and in §16.

---

## 10. Dashboard

Pages: `/campaigns` list · `/campaigns/new` (upload → template → fields → script preview/edit → approve → launch) · `/campaigns/[id]`.
Campaign page: totals cards (confirmed / declined / no answer / voicemail), stacked bar by language, table by segment, calls table (masked), **Retry non-responders** button, status badge, stretch: call drawer, Follow-up button.
Clean and polished matters (judges see this first). Loading skeletons, empty states, responsive.

---

## 11. Privacy (required by the brief)

| Control | Implementation |
|---|---|
| Encrypt contact lists | Fernet on `name_enc`, `phone_enc`; HMAC `phone_hash` for dedupe |
| Mask numbers | UI/API/logs show `+91•••••1234`; no raw phones in logs |
| Redact transcripts | Regex mask for phone-like digit runs and emails before storing |
| Auto-delete recordings/transcripts | Daily purge job and on startup: delete where `recording_expires_at < now`; defaults `RETENTION_DAYS=30` |
| Consent | `opted_out` honoured before every dial; recording notice in the opening line; calling-hours window |
| Erase | `DELETE /campaigns/{id}` |
| Data-flow slide (`docs/data-flow.md`) | Where voice, language and data processing happen |

**Honest data flow:** call audio and live conversation text are processed by ElevenLabs (speech recognition, LLM, speech synthesis) and the telephony provider; we check and state the data-residency / zero-retention settings of our plan. Contacts, transcripts and recordings are stored on our own server, encrypted. If Hugging Face script generation is enabled, it receives template text and campaign field values only, never contact data. Do **not** claim audio stays on our infrastructure. Future work: self-hosted speech stack.

---

## 12. Build agents

| Agent | Owns | Tasks |
|---|---|---|
| `lead` | this file, contracts, merges, demo script | T-01, T-13, T-15 |
| `backend` | `apps/api`, `templates/` | T-02, T-03, T-05, T-06, T-07, T-09 |
| `voice` | `apps/api/app/providers`, `templates/agent_prompt.md`, `evals/` | T-04, T-08 |
| `frontend` | `apps/web` | T-10, T-11, T-12 |
| `qa` | `scripts/`, tests, `docs/` | T-13, T-14, T-15 |

Pattern: lead slices tasks → specialists work in parallel on disjoint folders → qa checks → lead merges. One task = one branch `<agent>/T-xx-slug` = one PR.

Handoff note (PR description): `Task · From→To · Delivered · Contract touched · How to verify · Open issues`.

**Definition of done:** phase-1 workflow runs in mock mode · mypy/tsc/ruff clean · workflow/privacy tests pass · no PII/secrets in logs · `.env.example` updated · §7 updated if a contract changed · §13 and §16 updated. Do not edit README.md unless explicitly asked.

---

## 13. Task board

| ID | Task | Owner | Deps | Status |
|---|---|---|---|---|
| T-01 | Scaffold repo, compose (api+web), `.env.example`, CI | lead | — | done |
| T-02 | Models, SQLite, privacy service (encrypt, mask, redact, purge) | backend | T-01 | review |
| T-03 | Templates loader + CSV import (validate E.164, dedupe, encrypt) | backend | T-02 | review |
| T-04 | Language bake-off (en/hi/ml/ta): TTS model, voice, latency, accuracy | voice | ElevenLabs key + consented test numbers | blocked |
| T-05 | Mock/Hugging Face script generation + `POST /campaigns`, edit, approve | backend | T-03 | review |
| T-06 | `VoiceProvider` protocol + `MockProvider` + simulator | backend | T-02 | review |
| T-07 | Launch/retry queue with opt-out, call window, active-call concurrency, timeout reconciliation, and attempt limits | backend | T-06 | review |
| T-08 | `ElevenLabsProvider`: agent config, outbound call, overrides, webhook verify, tool endpoint | voice | T-06, number | wip |
| T-09 | Summary/calls endpoints | backend | T-07 | review |
| T-10 | App shell + campaign list + create wizard | frontend | T-01 | review |
| T-11 | Campaign page: cards, language chart, segment table, retry | frontend | T-09 | review |
| T-12 | Script preview/edit UI | frontend | T-05 | review |
| T-13 | `docs/data-flow.md` + privacy slide | lead | T-02 | review |
| T-14 | Accuracy table per language (`evals/lang_eval.py`) | qa | T-08 | blocked |
| T-15 | Demo rehearsal, seed data, runbook | qa | T-11 | wip |
| T-16 | External supervisor API, minimized snapshot, analytics, review queue | supervisor | T-07, T-09 | review |
| T-17 | Supervisor dashboard and human review actions | frontend | T-16 | review |
| T-18 | Guarded optional retry orchestration and operator runbook | supervisor | T-16 | review |
| S-01 | Follow-up campaign (reminder/update to confirmed) | backend+frontend | T-09 | todo |
| S-02 | Call detail drawer (transcript + outcome) | frontend | T-09 | todo |
| S-03 | Payment-reminder template, Tamil, cost/minutes | backend | T-08 | todo |
| D-01 | ElevenLabs hackathon RSVP simulation: organizer agent + AI participant personas for yes/no/unsure, persisted transcripts and CSV export | frontend+backend | T-01 | done |

Phase 1 critical path: T-01 → T-02 → T-06 → T-07 → T-09 → T-11 → T-15. Phase 2 starts with T-04 and then T-08 when provider credentials and consented numbers are available.
Cut order if late: S-03 → S-02 → S-01 → Tamil. Never cut: real call demo, outcome capture, voicemail/no-answer + retry, dashboard by language, privacy slide.

---

## 14. Env and commands

| Var | Purpose |
|---|---|
| `PROVIDER_MODE` | `mock` \| `elevenlabs` |
| `DATABASE_URL` | default `sqlite:///./data/swaram.db` |
| `FERNET_KEY`, `HMAC_PHONE_KEY` | encryption + phone hash |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID` | voice |
| `ELEVENLABS_WEBHOOK_SECRET`, `TOOL_SECRET` | webhook + tool auth |
| `TELEPHONY_KIND` | `twilio` \| `exotel`; must match the imported ElevenLabs number |
| `HF_TOKEN` | optional Hugging Face Inference Providers token for scripts and supervisor insights |
| `HF_MODEL` | default model ID `Qwen/Qwen3.8-27B:fastest` |
| `SCRIPT_PROVIDER_MODE` | `mock` \| `huggingface` (default `mock`) |
| `SUPERVISOR_READ_TOKEN` | Shared token for the minimized read-only snapshot endpoint |
| `SUPERVISOR_ACTION_TOKEN` | Shared token for the bounded supervisor retry endpoint |
| `SUPERVISOR_AUTO_RETRY` | `false` by default; explicitly enable bounded supervisor retries |
| `SUPERVISOR_API_URL` | Supervisor service URL, default `http://localhost:8100` |
| `SUPERVISOR_ANALYSIS_MODE` | `rules` default or `huggingface` aggregate analysis |
| `SUPERVISOR_MODEL` | optional model override; defaults to `HF_MODEL` |
| `PUBLIC_BASE_URL` | webhook/tool base (tunnel in dev) |
| `MAX_CONCURRENT`, `MAX_ATTEMPTS`, `CALL_TIMEOUT_S`, `CALL_WINDOW`, `RETENTION_DAYS` | behaviour |

```bash
docker compose up -d
uv run --directory apps/api --extra dev -- pytest tests -q
uv run --directory apps/api --extra dev -- ruff check app tests
uv run --directory apps/api --extra dev -- mypy app
pnpm --dir apps/web dev
docker compose exec api python -m app.seed_demo
uv run --directory apps/supervisor uvicorn app.main:app --reload --port 8100
python scripts/simulate.py --campaign <campaign-id> --n 200
python -m evals.lang_eval --langs en,hi,ml
cloudflared tunnel --url http://localhost:8000
```

---

## 15. Demo (3–4 min) and acceptance

1. Run the three ElevenLabs RSVP simulations; inspect tool-extracted outcomes and export the CSV.
2. Open the seeded workshop campaign; show scripts in ml/hi/en.
3. Create a campaign, import CSV contacts, preview/edit scripts, and approve.
4. Simulate calls and show dashboard totals by language and segment.
5. Retry non-responders and show attempt counts.
6. Swap to the clinic-reminder template to show reuse.
7. Explain the phase-1 mock data flow and phase-2 live voice data flow.

Phase 1 acceptance: mock run of 200 contacts fills the dashboard; CSV validation, phone masking, encryption, opt-out, retry limits, and campaign erasure are covered. Phase 2 acceptance: ≥1 consented real call each in en/hi/ml and an accuracy/latency table per language; no phone numbers in logs (grep test). Provider adapter and signed endpoints are implemented; live acceptance remains blocked until credentials, agent, imported number, and consented test contacts are configured.

---

## 16. Decisions, risks, questions, changelog

**Decisions**
| ID | Entry |
|---|---|
| D1 | ElevenLabs Agents = voice runtime (STT + LLM + TTS + turn-taking) |
| D2 | Campaign (not event lifecycle) is the core object; reminders/updates = Follow-up campaigns |
| D3 | SQLite + asyncio dialer + polling. No Temporal, Redis, MinIO, pgvector, RLS, Presidio |
| D4 | One ElevenLabs agent, per-call overrides + dynamic variables |
| D5 | Scripts generated once per language, human-approved, facts verbatim |
| D6 | Outcome captured by `record_outcome` tool; webhook is the safety net |
| D7 | Honest data-flow statement (§11); no "audio stays local" claim |
| D8 | Name: Swaram |
| D9 | RSVP demo runs the configured ElevenLabs organizer agent against ElevenLabs Agent Testing's AI-simulated participant for yes/no/unsure; it uses `record_outcome` for labels, stores the exact participant reply, and never calls telephony. |

**Risks**
| ID | Risk | Mitigation |
|---|---|---|
| R1 | No phone number/telephony by demo | Mock + recorded real call + browser provider |
| R2 | ElevenLabs can't take keypad input on our number type | Add a ~100-line Twilio `<Gather input="speech dtmf">` provider for keypad-only calls, or demo keypad in mock and say so |
| R3 | Malayalam quality | Bake-off first; use v3 for ml; fall back to hi/en for the live demo |
| R4 | Credit burn | Mock default, short test scripts, `MAX_CONCURRENT` low in dev |
| R5 | Webhook delivery flaky | Reconcile stuck calls via `get_conversation` |
| R6 | Scope creep | §3 Parked list; lead gatekeeps |

**Open questions:** Exotel SIP trunk available? Plan includes data residency/zero retention? DTMF behaviour on our number? Voicemail-detection tool available? Which demo numbers are verified/consented? Team roster for agent roles?

**Changelog**
| Date | Agent | Change |
|---|---|---|
| 2026-10-09 | lead | v1 created (event-lifecycle design) |
| 2026-10-09 | lead | v2: merged team's simple flow, campaign-centric, removed Temporal/Redis/MinIO/pgvector/RLS/Presidio/bandit/lifecycle, added Parked list, cut roster and tasks |
| 2026-10-09 | lead | v3: added the API and dashboard scaffold, Compose, env example, CI, and local setup docs; T-01 complete |
| 2026-10-09 | lead | Added standing rule: leave README.md unchanged unless explicitly requested |
| 2026-10-09 | lead | v4: implemented phase-1 campaign workflow, encrypted SQLite contacts, mock scripts/provider, simulation/retry dashboard, seed demo, privacy/data-flow notes; real calling is phase 2 |
| 2026-10-09 | lead | Source syntax, Compose config, and JSON manifests checked. Runtime tests/build pending because PyPI and npm registry connections are blocked in the current environment; phase-1 tasks marked review |
| 2026-10-09 | lead | v5: added ElevenLabs native Twilio outbound adapter with language/prompt overrides, persistent conversation IDs, authenticated outcome tool, signed post-call webhook handling, live-calling setup and data-flow docs; default stays mock |
| 2026-10-09 | lead | v6: hardened the core queue to enforce IST calling hours for live calls, cap active live calls, resume running campaigns after API restart, reconcile timed-out calls, handle call-initiation failure webhooks, expose accurate retryable counts, enforce campaign state transitions and template fields, and make the dashboard reflect provider mode with live-call confirmation; supervisor agent remains deferred |
| 2026-10-09 | lead | v7: added optional mock-first/Anthropic script generation without contact data, idempotent provider webhook receipts, clearer live/mock launch behavior, and updated setup notes; external supervisor remains deferred; live language accuracy acceptance is blocked pending provider credentials and consented test numbers |
| 2026-10-09 | lead | v8: approved a separate external supervisor service with minimized read-only snapshots, deterministic campaign analysis, human review cases, aggregate-only optional LLM analysis, and opt-in bounded retry orchestration |
| 2026-10-09 | lead | v9: implemented the separate supervisor API/service and review database, aggregate campaign analysis with optional Anthropic insights, human review dashboard, call deep links, minimized authenticated snapshots, and guarded opt-in auto-retries; test execution remains pending |
| 2026-10-09 | lead | v10: replaced optional Anthropic integrations with Hugging Face Inference Providers using Qwen3.8-27B for campaign script drafts and aggregate supervisor insights; mock generation and deterministic supervisor rules remain defaults |
| 2026-10-09 | Codex | Added contract and task for the synthetic hackathon RSVP simulation and export. |
| 2026-10-09 | Codex | Replaced the scripted RSVP demo with ElevenLabs Agent Testing simulations, scenario personas, `record_outcome` extraction, persisted transcripts, and CSV export; no phone calls are placed. |
