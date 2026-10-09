from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Swaram API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Tool-Secret"],
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/templates", tags=["templates"])
def list_templates() -> list[dict[str, object]]:
    return [
        {
            "id": "workshop_invite",
            "name": "Workshop invitation",
            "fields": ["topic", "venue", "date", "time", "organiser"],
            "outcomes": ["confirmed", "declined", "maybe", "callback", "optout"],
        },
        {
            "id": "clinic_reminder",
            "name": "Clinic appointment reminder",
            "fields": ["clinic", "date", "time", "organiser"],
            "outcomes": ["confirmed", "callback", "optout"],
        },
    ]
