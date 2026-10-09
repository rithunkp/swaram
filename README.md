# Swaram

Swaram is a multilingual calling campaign workspace for event organizers, clinics, and schools. This repository currently contains the project scaffold: a FastAPI service, a Next.js dashboard starting point, and a mock-first local development setup.

## Current state

- The dashboard is an initial responsive shell with an empty campaign state.
- The API exposes `/health` and the two planned starter templates at `/templates`.
- Campaign persistence, CSV import, script generation, calling, and analytics are not implemented yet. See [PROJECT_STATE.md](./PROJECT_STATE.md) for the product contracts and task board.
- The existing `assets/cover.png` is the project cover image.

- **Team Name**: Sector 21
- **Track**: PR 002 (Software)

Requirements: Docker Compose, or Python 3.12 and Node.js 22 for running services directly.

### Docker Compose

```bash
Copy-Item .env.example .env
docker compose up --build
```

Open the dashboard at <http://localhost:3000> and the API docs at <http://localhost:8000/docs>. The default provider mode is `mock`; no provider credentials are needed for the scaffold.

### Run services directly

```bash
uv run --directory apps/api uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd apps/web
npm install
npm run dev
```

## Project

- Event / track: DEFINE 4.0 · PR 002 (Software)
- Team: Sector 21
- Product direction and implementation contracts: [PROJECT_STATE.md](./PROJECT_STATE.md)

## Team

| Name | Focus | GitHub |
|---|---|---|
| Rithun K P | AI/ML, voice pipeline | [@rithunkp](https://github.com/rithunkp) |
| Ajmal M | Product development | [@24f2004489](https://github.com/24f2004489) |
| Muhammad Shifas | Product development | [@msnk-dev](https://github.com/msnk-dev) |
| Hareesh V | Product development | [@hv2337](https://github.com/hv2337) |
