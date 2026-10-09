# External campaign supervisor

The supervisor runs as a separate service. It polls Swaram's token-protected, read-only snapshot endpoint and keeps a local review queue and aggregate analysis in its own SQLite database. It never reads Swaram's database directly and never joins a live call.

## Local setup

Set the same two long, random values in `.env` for the API and Compose supervisor service:

```dotenv
SUPERVISOR_READ_TOKEN=<shared-read-token>
SUPERVISOR_ACTION_TOKEN=<separate-shared-action-token>
SUPERVISOR_AUTO_RETRY=false
SUPERVISOR_ANALYSIS_MODE=rules
```

Start the stack with `docker compose up -d --build`, then open `http://localhost:3000/supervisor`. The service polls every 15 seconds. The first sync may take one poll interval.

For optional aggregate-only model insights, create a Hugging Face fine-grained token with **Make calls to Inference Providers** permission, then set `SUPERVISOR_ANALYSIS_MODE=huggingface`, `HF_TOKEN`, and `HF_MODEL` in `.env`. `SUPERVISOR_MODEL` can override `HF_MODEL` for this service. The selected model receives campaign-level totals and grouped outcome rates, without campaign/contact identifiers, names, phone numbers, or transcripts. Deterministic code still owns case classification and retry eligibility.

## Decisions and human review

- The organizer reviews and approves every language script in the campaign page before launch.
- A completed `maybe` or `callback` outcome opens a human review item immediately.
- `no_answer`, `voicemail`, or `failed` outcomes stay retry-eligible until the configured attempt limit. After the limit, the supervisor opens a human review item.
- Opt-outs are excluded from retries and are not put in the unresolved queue.
- The analysis highlights eligible retries, failure rates of 20% or more, and response-rate gaps of 25 percentage points or more when each compared language has at least five contacts.
- A reviewer can open the exact campaign call from a case, inspect the redacted transcript, and correct the outcome in Swaram. A saved opt-out cannot be reversed. Resolving or dismissing the supervisor case does not itself rewrite the call outcome; the supervisor stores no free-text notes.

Retries remain manual by default. The Supervisor page's retry action uses Swaram's existing retry endpoint and asks for confirmation before live calls. To enable automatic bounded retries after a campaign completes, set `SUPERVISOR_AUTO_RETRY=true`. The API requires the separate action token and rechecks eligibility; Swaram's queue continues to enforce call hours, opt-outs, and `MAX_ATTEMPTS`. Enable this only when the organizer has authorized the campaign audience for those retries.

The services are intended for the current single-operator local deployment. Add user authentication and tenant-level access controls before exposing the supervisor or review endpoints to a public network.
