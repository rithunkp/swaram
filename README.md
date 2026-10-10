# DEFINE 4.0

The official project submission repository for **DEFINE 4.0 — The World's Realest Hackathon**.

---
# Swaram

<!-- Add your project cover image below -->

![Project Cover](./assets/cover.png)

## Team Information

- **Team Name**: Sector 21
- **Track**: PR 002 (Software)

## Team Members

| Name | Role | GitHub | LinkedIn |
|------|------|--------|----------|
| Rithun K P | AI/ML, Voice Pipeline | [@rithunkp](https://github.com/rithunkp) | [Profile](https://linkedin.com/in/rithun-kp) |
| Ajmal M | Role | [@24f2004489](https://github.com/24f2004489) | [Profile](https://linkedin.com/in/ajmal-m-282670284) |
| Muhammad Shifas | Role | [@msnk-dev](https://github.com/msnk-dev) | [Profile](https://linkedin.com/in/muhammed-shifas-nk-62601a409) |
| Hareesh V | Role | [@hv2337](https://github.com/hv2337) | [Profile](https://linkedin.com/in/hareesh2337v) |

---

# Project Details

## Overview

Swaram lets an organiser upload a contact list, pick a template, and phone everyone in the language they speak. It understands each reply, shows who confirmed, and retries the rest with one click. The same flow works for clinic reminders, school notices and payment follow-ups.

## Problem Statement

Institutions run seminars and workshops across cities, and most still chase attendance with phone calls, spreadsheets and mass messages.

- **What is the problem?** Calling hundreds or thousands of people in their own language, noting who is coming, and telling them when plans change takes a lot of time and money, and mistakes creep in.
- **Who is affected?** Organisers, clinics, schools and finance teams, along with the people on the other end who get calls in the wrong language or at the wrong time.
- **Why does it matter?** Every missed update or unreachable contact is an empty seat or a skipped appointment. Contact lists and call recordings are also personal data, and they often get handled carelessly.
- **Limits of existing solutions:** IVR blasts speak one language and can't listen. Call centres don't scale. Most tools only track whether a call was made, not whether the person is coming, so a venue change means redoing the campaign by hand.

## Solution

Swaram turns an **event** into a campaign. The organiser uploads contacts and picks a template, an AI step writes the script in each language (Malayalam, Hindi and English to start), and the organiser reviews and approves it. A voice agent then calls everyone: facts like the date and venue are read exactly as approved, and the AI only works out what the person says back. People can speak their answer or press a key, and voicemail and no-answer are logged as outcomes that can be retried. The dashboard shows confirmed, declined, no-answer and voicemail by language and segment, with one-click retry for non-responders. Reminders and updates go out the same way, as follow-up campaigns to the people who confirmed. Contact data is encrypted and masked, transcripts are redacted, and recordings are deleted automatically. Call audio is handled by our voice provider, ElevenLabs, and everything we store stays on our own server.

---

# Demo

### Demo Video

[Watch Project Demo](https://www.youtube.com/watch?v=VIDEO_ID)


### Screenshots

<!-- Add screenshots of your project here -->

![Screenshot 1](./assets/screenshot-1.png)

![Screenshot 2](./assets/screenshot-2.png)

![Screenshot 3](./assets/screenshot-3.png)

---

# Live Project

[Visit Live Project](https://your-project-url.com/)

---

# Technical Implementation

## Technologies Used

| Category | Technologies |
|----------|--------------|
| **Frontend** | Next.js 15, React 19, TypeScript |
| **Backend** | Python 3.12, FastAPI, Uvicorn |
| **Database** | SQLite, SQLAlchemy |
| **APIs / Services** | ElevenLabs voice API, Exotel, HTTPX |
| **AI / ML** | ElevenLabs voice agent; Hugging Face model support for supervisor analysis |
| **DevOps / Deployment** | Docker, Docker Compose |
| **Other Tools** | Pydantic Settings, Cryptography, pytest, Ruff, mypy |

## System Architecture

<!-- Add your architecture diagram here -->

![System Architecture](./assets/architecture.png)

## Key Features

- Create calling campaigns from templates and easily upload contacts.
- Prepare scripts in English, Hindi, and Malayalam, then review and approve them before launch.
- Simulate calls and record outcomes such as confirmed, declined, maybe, callback, or opt-out.
- Track campaign results by language, segment, and call status; export results to CSV and retry non-responders.
- Review campaign activity and cases requiring human review in the supervisor dashboard.

---

# Setup Instructions

## Prerequisites

- Git
- Docker Desktop with Docker Compose
- For the optional RSVP Agent Testing demo: an ElevenLabs API key and Agent ID

To run without Docker, install Python 3.12+, `uv`, Node.js, and npm.

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/rithunkp/swaram.git

cd swaram
```

### 2. Configure environment

```bash
cp .env.example .env
```

Set distinct values for `SUPERVISOR_READ_TOKEN` and `SUPERVISOR_ACTION_TOKEN` in `.env`. The default `PROVIDER_MODE=mock` keeps the demo from placing real calls.

### 3. Start the application

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). To stop the services, press `Ctrl+C`, then run:

```bash
docker compose down
```

Campaign data is kept in Docker volumes. To erase local campaign and supervisor data, run `docker compose down -v`.

### Optional: run without Docker

Start the API and supervisor in separate terminals from the repository root:

```bash
uv run --directory apps/api uvicorn app.main:app --reload --port 8000
```

```bash
uv run --directory apps/supervisor uvicorn app.main:app --reload --port 8100
```

Then start the frontend in another terminal:

```bash
cd apps/web
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). For the optional RSVP simulation, set `ELEVENLABS_API_KEY` and `ELEVENLABS_AGENT_ID` in `.env` before starting the API.
