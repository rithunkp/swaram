# Swaram data flow

## Phase 1 demo

The local dashboard sends campaign details and a CSV contact list to the FastAPI service. By default, the service validates the CSV and creates language-specific mock scripts without contacting an LLM. If `SCRIPT_PROVIDER_MODE=huggingface` is explicitly configured, it sends only the selected template, language, approved question, and campaign field values to Hugging Face Inference Providers; it never sends the contact list. An organizer reviews and approves generated scripts before launch. See [script generation](script-generation.md) for setup. The service encrypts contact names and phone numbers before storing them in SQLite and keeps only an HMAC of each phone number for deduplication. The demo provider simulates call outcomes; it does not place calls. Contact numbers are masked in call lists, and simulated transcripts are redacted before storage. Contact details and database encryption keys are stored in the local `data/` directory; that directory is excluded from Git.

The Hackathon RSVP demo uses ElevenLabs Agent Testing. Clicking **Start 3-call simulation** runs the configured organizer agent against ElevenLabs' AI-simulated participant in three natural-language personas: yes, no, and unsure. Swaram reads the organizer agent's `record_outcome` tool call to capture `confirmed`, `declined`, or `maybe`, then stores the generated transcript and exact participant wording in `demo_rsvp_calls`; a run is tracked in `demo_rsvp_runs`. Simulation test definitions are created once per scenario and reused. Results can be exported as CSV. This uses the ElevenLabs API and may consume plan usage, but Agent Testing does not use Exotel, a PSTN number, or the microphone. It returns text transcripts, not live audio. For an audible human-to-agent browser conversation, use the separate [browser voice demo](browser-voice-demo.md).

The external supervisor is a separate service. It reads a token-protected snapshot containing campaign states and opaque contact/call references, with language, segment, attempt, outcome, and opt-out metadata. It does not receive contact names, phone numbers, or transcripts and stores its own campaign summaries and human-review queue. Optional Hugging Face analysis receives aggregate counts and rates only. Automatic retries are disabled by default; when enabled, the supervisor can request only Swaram's bounded retry operation.

For a deployed service, provide `FERNET_KEY` and `HMAC_PHONE_KEY` through the deployment secret manager. The local generated keys are suitable only for a local demo and are stored beside the local database.

## Phase 2 live calling

When `PROVIDER_MODE=elevenlabs`, Swaram sends the destination number, contact name, first message, language, approved campaign facts, and a non-PII call ID to the ElevenLabs outbound-call API. ElevenLabs and its telephony provider process call audio and live conversation text. Outcome fields arrive at Swaram's authenticated tool endpoint. A signed post-call webhook sends conversation metadata and transcript text; Swaram verifies its HMAC signature, redacts phone numbers and email addresses, and stores the redacted transcript until retention cleanup. Call recording is explicitly disabled in the outbound request, and Swaram does not store audio. Review the vendor plan's data-residency and retention settings before using real contacts. Script generation stays mock-backed unless the Hugging Face provider is explicitly enabled.

See [live-calling.md](live-calling.md) for agent setup, credentials, consented test steps, and current limits.

## Retention and opt-out

Transcript text is cleared when its call retention date has passed, on service startup. Calls to contacts marked opted out in the imported CSV are skipped. Campaign deletion removes its contacts and calls through the campaign relationship.
