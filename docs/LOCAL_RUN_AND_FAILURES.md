# Local run status and known limitations

Updated: 10 October 2026

## Verified end to end

| Component | Result |
| --- | --- |
| Web production build | Passed; Next.js compiled routes and type checks |
| API source syntax | Passed with Python bytecode compilation |
| API and dashboard | HTTP 200 on `127.0.0.1:18991` and `127.0.0.1:3010` |
| CSV upload and validation | Passed with five synthetic contacts and `user_id`, name, phone, language, and segment columns |
| Script approval | Passed for English, Hindi, and Malayalam |
| ElevenLabs campaign simulation | 5 of 5 conversations completed; concurrency cap 2 |
| Outcome extraction | 2 confirmed, 1 declined, 1 unsure, 1 callback request; exact reply and transcript present for all five |
| Language check | Organizer and participant conversations used the assigned English, Hindi, or Malayalam language |
| Results export | Passed; five rows saved as `Swaram-synthetic-rsvp-results.csv` |
| Real phone calls | None; telephony provider stayed in `mock` mode |

Campaign: `9c85eb64-4b3a-42da-9a1b-e10f8e602f5b`. The first upload attempt was rejected because a copy of the dummy CSV had lost the `+` E.164 prefix. I corrected and quoted the phone cells, re-uploaded successfully, then ran the campaign. No campaign was created from the rejected upload.

## Contact campaign behavior

Upload a UTF-8 CSV with `user_id,name,phone,language` columns; `segment` is optional. Each contact gets one independently simulated conversation in their selected language. The AI participant chooses a plausible response naturally; the campaign does not preassign yes/no/unsure outcomes. The ElevenLabs organizer records `confirmed`, `declined`, `maybe`, `callback`, `optout`, or `other`, together with the participant's exact reply and transcript.

Swaram stores one call row per contact, atomically claims queued rows before processing, and shares a server-wide concurrency limit set by `MAX_CONCURRENT`. The campaign activity table exposes user ID, masked number, queued/in-progress/finished state, outcome, and transcript. Use **Export results CSV** for contact details, classification, exact reply, transcript, language, and call state. `ELEVENLABS_API_KEY` and `ELEVENLABS_AGENT_ID` must be in the API environment. Uploaded phone numbers are not sent to ElevenLabs for these simulations. The sample CSV uses fictional reserved `555-010x` phone numbers.

The API uses a separate campaign organizer agent per selected language and does not modify the configured source agent. ElevenLabs account plan usage may apply to each simulated conversation.

## Known limitations

1. **Exotel authorization:** the previous live-provider attempt returned HTTP 403. This run does not validate Exotel credentials, caller number, account permissions, or Voicebot applet setup.
2. **No live telephony validation:** call audio, keypad capture, consent, and delivery to a test phone remain unverified. This run exercises simulated text conversations, not PSTN audio.
3. **Language quality:** the assigned languages were observed in these five test transcripts. Voice quality depends on the source agent's selected voice and ElevenLabs language/model support. Non-English campaign script generation beyond local mock templates requires `SCRIPT_PROVIDER_MODE=huggingface`, a working Hugging Face token/model, and human review.
4. **Docker:** Docker Desktop is not installed, so the local application runs directly.
5. **Production deployment:** webhooks and live provider callbacks need a stable public HTTPS deployment; localhost is not public.

## Current local services

- Campaign results: <http://127.0.0.1:3010/campaigns/9c85eb64-4b3a-42da-9a1b-e10f8e602f5b>
- Create another campaign: <http://127.0.0.1:3010/campaigns/new>
- API health: <http://127.0.0.1:18991/health>
- API database: `apps/api/data/swaram-rsvp-run.db`
- Telephony mode: `mock` (no phone calls)
- Concurrency: 2 (`MAX_CONCURRENT=2`)

The source `.env` remains local. The packaged source archive excludes `.env*` files (except `.env.example`), local databases, logs, generated data, `node_modules`, and build artifacts.
