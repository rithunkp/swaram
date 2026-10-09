# Swaram demo runbook

## Start

Copy `.env.example` to `.env`, then run `docker compose up --build`. Open <http://localhost:3000>. The UI and API default to mock mode; the demo never dials phone numbers.

To prefill a 200-contact campaign for Compose, run `docker compose exec api python -m app.seed_demo`, then refresh the page. For a directly run API, use `uv run --directory apps/api python ../../scripts/seed_demo.py` from the repository root. Alternatively, create a fresh campaign in the UI with the sample CSV.

## Four-minute walkthrough

1. Open the Community Design Workshop campaign, showing language, segment, and outcome totals.
2. Expand each script to show English, Hindi, and Malayalam copy. Use a new campaign to show template choice, event details, and CSV import.
3. In the new draft, edit a script and approve all language scripts.
4. Click **Simulate campaign** and watch the outcome cards and masked call list populate.
5. Click **Retry non-responders** and show the next attempt number.
6. Explain that this phase is simulated; the separate live-calling phase will require provider setup and consented test contacts.

## Reset local demo data

Remove the `swaram-data` volume with `docker compose down -v` only when you want to erase all local campaigns and generated encryption keys. Recreate the seeded example by running the seed command again.
