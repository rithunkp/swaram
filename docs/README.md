# Swaram documentation

Start with the guide that matches the work you are doing:

## Run and demo

- [Local run and known limitations](LOCAL_RUN_AND_FAILURES.md) — Windows setup without Docker, verified local status, and unresolved live-calling constraints.
- [Demo runbook](demo-runbook.md) — the campaign workflow to show during a demo.
- [Browser voice demo](browser-voice-demo.md) — talk to the configured ElevenLabs agent from the browser; this does not place a phone call.

## System behavior

- [Campaign data flow](data-flow.md) — CSV import through call results, privacy handling, and the live provider boundary.
- [Script generation](script-generation.md) — mock and optional Hugging Face script generation.
- [External supervisor](supervisor.md) — separate service, minimized snapshots, analysis, human review, and guarded retries.

## Live telephony

- [Live calling setup](live-calling.md) — ElevenLabs/telephony configuration, webhooks, and consented test steps. Live calling requires valid provider credentials and public HTTPS endpoints.

Keep `.env`, local databases, generated build files, and real contact lists out of Git. The example environment file contains placeholders only.
