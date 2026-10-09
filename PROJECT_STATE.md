# Swaram — Project State

> Last updated: 2026-10-10 · Status: Core product implemented; Exotel setup and live-call validation remain.
> Do not edit `README.md` unless the user asks. Keep this file as the short source of truth for current status and next steps.

## Current state

At review, the repository was on `main` at commit `8a0e56c` (`Build multilingual RSVP demos and supervisor`) with no pending changes. The main application and its demo/supervisor flows are implemented. Keep the scope focused; the remaining work is provider setup and end-to-end live-call validation, not another architecture or feature expansion.

## What is implemented

- Campaign creation from CSV, templates, multilingual draft scripts, review/approval, campaign results, retry controls, transcript review, and CSV export.
- Privacy basics: encrypted contact details, masked numbers, transcript redaction/retention, opt-out handling, calling windows, and retry limits.
- `PROVIDER_MODE=mock`: campaign conversations run through ElevenLabs Agent Testing; they do not dial uploaded phone numbers. This mode needs an ElevenLabs API key and agent ID.
- `PROVIDER_MODE=elevenlabs`: live outbound campaign adapter, `record_outcome` tool endpoint, signed webhook handling, and Twilio/Exotel endpoint selection are implemented.
- RSVP demo: three AI participant scenarios (yes, no, unsure), saved conversations/outcomes, and CSV export; no phone calls.
- Browser voice demo: direct browser-to-ElevenLabs conversation; it does not test Exotel or campaign dialing.
- Separate campaign supervisor with minimized snapshots, analysis, human review, and optional bounded retries. Automatic retries are off by default.
- Script generation defaults to local mock copy; Hugging Face generation is optional.

## Remaining work: Exotel setup and validation

The Exotel provider option is present in code. A previous live-provider attempt returned HTTP 403, so Exotel authorization and actual phone delivery are not confirmed.

1. Confirm Exotel account access and outbound-call permissions; configure an eligible Exotel number and import/connect it in ElevenLabs.
2. Set `PROVIDER_MODE=elevenlabs`, `TELEPHONY_KIND=exotel`, and the matching ElevenLabs phone-number ID in the local `.env`.
3. Configure public HTTPS callback/tool URLs, webhook signing secret, and tool secret as described in `docs/live-calling.md`.
4. With consented team test numbers, verify one real call end to end: delivery, audio/language, outcome tool, webhook, opt-out, and keypad behavior. Then record language quality and latency before claiming them as validated.

Until those steps pass, keep `PROVIDER_MODE=mock`; no real calls are made in mock mode. Do not use real campaign contacts for setup tests without consent.

## Local run

- Copy `.env.example` to `.env` and keep `PROVIDER_MODE=mock` for demos.
- Run `docker compose up --build -d`.
- Open the campaign app at `http://localhost:3000`; the supervisor is at `http://localhost:8100`.
- For mock campaign conversations and the RSVP simulation, configure `ELEVENLABS_API_KEY` and `ELEVENLABS_AGENT_ID`. These are text simulations and may use ElevenLabs plan credits, but do not dial a phone number.
- See `docs/demo-runbook.md`, `docs/live-calling.md`, and `docs/LOCAL_RUN_AND_FAILURES.md` for walkthrough, live setup, and recorded validation details.

## Recorded verification and limits

`docs/LOCAL_RUN_AND_FAILURES.md` records a successful local production build and a five-contact English/Hindi/Malayalam Agent Testing campaign with outcomes and CSV export. It also records that no phone calls were placed and that the previous Exotel attempt returned HTTP 403. This confirms the simulation path only; it does not establish real Exotel delivery, live audio quality, keypad support, or language accuracy/latency targets.

## Deferred

Do not add more infrastructure or expand product scope for this phase. Follow-up campaigns, Tamil, additional analytics, and public multi-user authentication remain deferred unless the user reprioritizes them. Do not expose the single-operator app or supervisor publicly without adding authentication and access controls.

## Changelog

| Date | Change |
|---|---|
| 2026-10-10 | Updated current state for campaign workflows, Agent Testing demos, browser voice, external supervisor, and implemented Twilio/Exotel provider selection. Exotel account authorization and live-call validation remain the final work. |
