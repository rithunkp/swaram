# Swaram data flow

## Phase 1 demo

The local dashboard sends campaign details and a CSV contact list to the FastAPI service. The service validates the CSV, creates language-specific mock scripts, encrypts contact names and phone numbers before storing them in SQLite, and keeps only an HMAC of each phone number for deduplication. The demo provider simulates call outcomes; it does not place calls or send data to voice or LLM vendors. Contact numbers are masked in call lists, and simulated transcripts are redacted before storage. Contact details and database encryption keys are stored in the local `data/` directory; that directory is excluded from Git.

For a deployed service, provide `FERNET_KEY` and `HMAC_PHONE_KEY` through the deployment secret manager. The local generated keys are suitable only for a local demo and are stored beside the local database.

## Phase 2 live calling

When `PROVIDER_MODE=elevenlabs`, Swaram sends the destination number, contact name, first message, language, approved campaign facts, and a non-PII call ID to the ElevenLabs outbound-call API. ElevenLabs and its telephony provider process call audio and live conversation text. Outcome fields arrive at Swaram's authenticated tool endpoint. A signed post-call webhook sends conversation metadata and transcript text; Swaram verifies its HMAC signature, redacts phone numbers and email addresses, and stores the redacted transcript until retention cleanup. Call recording is explicitly disabled in the outbound request, and Swaram does not store audio. Review the vendor plan's data-residency and retention settings before using real contacts. Script generation remains mock-backed and sends no data to Claude.

See [live-calling.md](live-calling.md) for agent setup, credentials, consented test steps, and current limits.

## Retention and opt-out

Transcript text is cleared when its call retention date has passed, on service startup. Calls to contacts marked opted out in the imported CSV are skipped. Campaign deletion removes its contacts and calls through the campaign relationship.
