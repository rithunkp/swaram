import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, TypedDict

from cryptography.fernet import Fernet
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from app.providers import CallRequest, ElevenLabsProvider, MockProvider, VoiceProvider

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/swaram.db")
if DATABASE_URL.startswith("sqlite:///"):
    db_file = Path(DATABASE_URL.removeprefix("sqlite:///"))
    db_file.parent.mkdir(parents=True, exist_ok=True)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    template_id: Mapped[str] = mapped_column(String(80))
    fields: Mapped[str] = mapped_column(Text)
    languages: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    contacts: Mapped[list["Contact"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    scripts: Mapped[list["Script"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    name_enc: Mapped[str] = mapped_column(Text)
    phone_enc: Mapped[str] = mapped_column(Text)
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    language: Mapped[str] = mapped_column(String(4))
    segment: Mapped[str] = mapped_column(String(120), default="General")
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    campaign: Mapped[Campaign] = relationship(back_populates="contacts")
    calls: Mapped[list["Call"]] = relationship(back_populates="contact", cascade="all, delete-orphan")


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    language: Mapped[str] = mapped_column(String(4))
    first_message: Mapped[str] = mapped_column(Text)
    voicemail_message: Mapped[str] = mapped_column(Text)
    key_points: Mapped[str] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    campaign: Mapped[Campaign] = relationship(back_populates="scripts")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    input_mode: Mapped[str | None] = mapped_column(String(12), nullable=True)
    party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    callback_time: Mapped[str | None] = mapped_column(String(160), nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    recording_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    contact: Mapped[Contact] = relationship(back_populates="calls")


Base.metadata.create_all(engine)
# create_all does not add columns to databases created by earlier versions.
with engine.begin() as connection:
    if DATABASE_URL.startswith("sqlite"):
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(calls)")}
        if "conversation_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE calls ADD COLUMN conversation_id VARCHAR(120)")
        if "party_size" not in columns:
            connection.exec_driver_sql("ALTER TABLE calls ADD COLUMN party_size INTEGER")
        if "callback_time" not in columns:
            connection.exec_driver_sql("ALTER TABLE calls ADD COLUMN callback_time VARCHAR(160)")
app = FastAPI(title="Swaram API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Tool-Secret"],
)

LANGUAGES = {"en", "hi", "ml"}
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))
OUTCOMES = ["confirmed", "declined", "maybe", "callback", "optout", "no_answer", "voicemail", "failed"]


class TemplateSpec(TypedDict):
    id: str
    name: str
    fields: list[str]
    outcomes: list[str]


TEMPLATES: dict[str, TemplateSpec] = {
    "workshop_invite": {
        "id": "workshop_invite",
        "name": "Workshop invitation",
        "fields": ["topic", "venue", "date", "time", "organiser"],
        "outcomes": ["confirmed", "declined", "maybe", "callback", "optout"],
    },
    "clinic_reminder": {
        "id": "clinic_reminder",
        "name": "Clinic appointment reminder",
        "fields": ["clinic", "date", "time", "organiser"],
        "outcomes": ["confirmed", "callback", "optout"],
    },
}
FERNET: Fernet
PHONE_HMAC_KEY: bytes
PROVIDER_MODE = os.getenv("PROVIDER_MODE", "mock").lower()
if PROVIDER_MODE == "elevenlabs":
    required_env = (
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_AGENT_ID",
        "ELEVENLABS_PHONE_NUMBER_ID",
        "ELEVENLABS_WEBHOOK_SECRET",
        "TOOL_SECRET",
    )
    missing_env = [key for key in required_env if not os.getenv(key)]
    if missing_env:
        raise RuntimeError(f"PROVIDER_MODE=elevenlabs requires: {', '.join(missing_env)}")
    PROVIDER: VoiceProvider = ElevenLabsProvider(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        agent_id=os.environ["ELEVENLABS_AGENT_ID"],
        phone_number_id=os.environ["ELEVENLABS_PHONE_NUMBER_ID"],
        webhook_secret=os.environ["ELEVENLABS_WEBHOOK_SECRET"],
    )
elif PROVIDER_MODE == "mock":
    PROVIDER = MockProvider()
else:
    raise RuntimeError("PROVIDER_MODE must be 'mock' or 'elevenlabs'")
PURGE_TASK: asyncio.Task[None] | None = None


def load_secret(filename: str, env_name: str, generated: bytes) -> bytes:
    value = os.getenv(env_name)
    if value:
        return value.encode()
    key_path = Path("data") / filename
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_bytes(generated)
    return key_path.read_bytes()


@app.on_event("startup")
async def initialize() -> None:
    global FERNET, PHONE_HMAC_KEY, PURGE_TASK
    fernet_key = load_secret(".fernet.key", "FERNET_KEY", Fernet.generate_key())
    FERNET = Fernet(fernet_key)
    PHONE_HMAC_KEY = load_secret(".phone-hmac.key", "HMAC_PHONE_KEY", os.urandom(32))
    with Session(engine) as session:
        session.execute(
            Call.__table__.update()
            .where(Call.recording_expires_at < datetime.now(UTC))
            .values(transcript_redacted=None)
        )
        session.commit()
    if PURGE_TASK is None or PURGE_TASK.done():
        PURGE_TASK = asyncio.get_running_loop().create_task(purge_loop())


async def purge_loop() -> None:
    while True:
        await asyncio.sleep(24 * 60 * 60)
        with Session(engine) as session:
            session.execute(
                Call.__table__.update()
                .where(Call.recording_expires_at < datetime.now(UTC))
                .values(transcript_redacted=None)
            )
            session.commit()


@app.on_event("shutdown")
async def shutdown() -> None:
    global PURGE_TASK
    if PURGE_TASK and not PURGE_TASK.done():
        PURGE_TASK.cancel()
        PURGE_TASK = None


def seal(value: str) -> str:
    return FERNET.encrypt(value.encode()).decode()


def reveal(value: str) -> str:
    return FERNET.decrypt(value.encode()).decode()


def phone_hash(value: str) -> str:
    return hmac.new(PHONE_HMAC_KEY, value.encode(), hashlib.sha256).hexdigest()


def mask_phone(value: str) -> str:
    if value.startswith("+91"):
        return f"+91•••••{value[-4:]}"
    return f"+••••••{value[-4:]}"


def redact(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
    return re.sub(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)", "[phone]", text)


def to_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def campaign_summary(campaign_id: str, session: Session) -> dict[str, object]:
    contacts = list(session.scalars(select(Contact).where(Contact.campaign_id == campaign_id)))
    calls = list(session.scalars(select(Call).where(Call.campaign_id == campaign_id)))
    latest: dict[str, Call] = {}
    for call in sorted(calls, key=lambda item: item.attempt_no):
        latest[call.contact_id] = call
    total = len(contacts)
    done = sum(1 for call in calls if call.state == "done")
    counts: dict[str, int] = {outcome: 0 for outcome in OUTCOMES}
    by_language: dict[str, dict[str, int]] = {}
    by_segment: dict[str, dict[str, int]] = {}
    for contact in contacts:
        outcome = (latest[contact.id].outcome or "queued") if contact.id in latest else "queued"
        if outcome in counts:
            counts[outcome] += 1
        by_language.setdefault(contact.language, {})[str(outcome)] = by_language.setdefault(contact.language, {}).get(str(outcome), 0) + 1
        by_segment.setdefault(contact.segment, {})[str(outcome)] = by_segment.setdefault(contact.segment, {}).get(str(outcome), 0) + 1
    return {
        "total_contacts": total,
        "completed_calls": done,
        "outcomes": counts,
        "by_language": by_language,
        "by_segment": by_segment,
    }


def campaign_detail(campaign: Campaign, session: Session) -> dict[str, object]:
    contacts = list(session.scalars(select(Contact).where(Contact.campaign_id == campaign.id)))
    scripts = list(session.scalars(select(Script).where(Script.campaign_id == campaign.id).order_by(Script.language)))
    summary = campaign_summary(campaign.id, session)
    return {
        "id": campaign.id,
        "name": campaign.name,
        "template_id": campaign.template_id,
        "fields": json.loads(campaign.fields),
        "languages": json.loads(campaign.languages),
        "status": campaign.status,
        "created_at": campaign.created_at.isoformat(),
        "contact_count": len(contacts),
        "approved": bool(scripts) and all(script.approved for script in scripts),
        "scripts": [
            {
                "language": script.language,
                "first_message": script.first_message,
                "voicemail_message": script.voicemail_message,
                "key_points": script.key_points,
                "approved": script.approved,
            }
            for script in scripts
        ],
        "summary": summary,
    }


def script_copy(language: str, template_id: str, fields: dict[str, str]) -> tuple[str, str]:
    if template_id == "clinic_reminder":
        if language == "hi":
            return (f"नमस्ते, {fields.get('organiser', 'Swaram')} की ओर से {fields.get('clinic', 'क्लिनिक')} का {fields.get('date', '')} को {fields.get('time', '')} बजे अपॉइंटमेंट याद दिला रहे हैं। क्या आप आ पाएँगे?", "आपके अपॉइंटमेंट की याद दिलाने के लिए कॉल किया था।")
        if language == "ml":
            return (f"നമസ്കാരം, {fields.get('organiser', 'Swaram')} അറിയിക്കുന്നു: {fields.get('clinic', 'ക്ലിനിക്')} സന്ദർശനം {fields.get('date', '')} {fields.get('time', '')} മണിക്ക് ആണ്. നിങ്ങൾക്ക് വരാനാകുമോ?", "നിങ്ങളുടെ അപ്പോയിന്റ്മെന്റ് ഓർമ്മിപ്പിക്കാൻ വിളിച്ചതാണ്.")
        return (f"Hello, {fields.get('organiser', 'Swaram')} is reminding you about your appointment at {fields.get('clinic', 'the clinic')} on {fields.get('date', '')} at {fields.get('time', '')}. Can you attend?", "We called with a reminder about your appointment.")
    if language == "hi":
        return (f"नमस्ते, {fields.get('organiser', 'Swaram')} की ओर से {fields.get('topic', 'कार्यशाला')} के बारे में कॉल है। यह {fields.get('date', '')} को {fields.get('time', '')} बजे {fields.get('venue', '')} में होगा। क्या आप आएँगे?", "कार्यशाला के निमंत्रण के लिए कॉल किया था। अधिक जानकारी के लिए आयोजक से संपर्क करें।")
    if language == "ml":
        return (f"നമസ്കാരം, {fields.get('organiser', 'Swaram')} അറിയിക്കുന്നു: {fields.get('topic', 'ശില്പശാല')} {fields.get('date', '')} {fields.get('time', '')} മണിക്ക് {fields.get('venue', '')} ൽ നടക്കും. നിങ്ങൾ പങ്കെടുക്കുമോ?", "ശില്പശാലയിലേക്ക് ക്ഷണിക്കാൻ വിളിച്ചതാണ്. കൂടുതൽ വിവരങ്ങൾക്ക് സംഘാടകരെ ബന്ധപ്പെടുക.")
    return (f"Hello, this is a message from {fields.get('organiser', 'Swaram')}. Join us for {fields.get('topic', 'our workshop')} at {fields.get('venue', '')} on {fields.get('date', '')} at {fields.get('time', '')}. Will you attend?", "We called to invite you to our workshop. Please contact the organizer for details.")


class ScriptUpdate(BaseModel):
    first_message: str = Field(min_length=1, max_length=3000)
    voicemail_message: str = Field(min_length=1, max_length=1000)
    key_points: str = Field(default="", max_length=3000)


class OutcomeInput(BaseModel):
    call_id: str
    outcome: str
    input_mode: str | None = None
    duration_s: int | None = Field(default=None, ge=0, le=86400)
    party_size: int | None = Field(default=None, ge=1, le=10000)
    callback_time: str | None = Field(default=None, max_length=160)


@app.post("/voice/tools/record_outcome", tags=["voice"])
def record_outcome(body: OutcomeInput, request: Request) -> dict[str, bool]:
    configured_secret = os.getenv("TOOL_SECRET", "")
    supplied_secret = request.headers.get("X-Tool-Secret", "")
    if not configured_secret or not hmac.compare_digest(configured_secret, supplied_secret):
        raise HTTPException(401, "Invalid tool credentials")
    if body.outcome not in {"confirmed", "declined", "maybe", "callback", "optout"}:
        raise HTTPException(422, "Unsupported call outcome")
    if body.input_mode not in {None, "speech", "keypad"}:
        raise HTTPException(422, "input_mode must be speech or keypad")
    with Session(engine) as session:
        call = session.get(Call, body.call_id)
        if call is None:
            raise HTTPException(404, "Call not found")
        # Repeated tool calls are safe: the first outcome is authoritative.
        if call.outcome is None:
            call.outcome = body.outcome
            call.input_mode = body.input_mode if body.input_mode in {"speech", "keypad"} else None
            call.duration_s = body.duration_s
            call.party_size = body.party_size
            call.callback_time = body.callback_time
            if body.outcome == "optout":
                call.contact.opted_out = True
        session.commit()
    return {"ok": True}


@app.post("/webhooks/elevenlabs", tags=["webhooks"])
async def elevenlabs_webhook(request: Request) -> dict[str, bool]:
    raw_body = await request.body()
    if not PROVIDER.verify_webhook(request.headers, raw_body):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    if not isinstance(event, dict):
        raise HTTPException(400, "Webhook body must be a JSON object")
    if event.get("type") != "post_call_transcription":
        return {"ok": True}
    data = event.get("data") or {}
    if not isinstance(data, dict):
        raise HTTPException(400, "Webhook data must be a JSON object")
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        raise HTTPException(422, "Webhook missing conversation_id")
    with Session(engine) as session:
        call = session.scalar(select(Call).where(Call.conversation_id == conversation_id))
        if call is None:
            # Acknowledge safely: delivery may arrive before transaction commit or
            # for a call removed by retention/deletion.
            return {"ok": True}
        call.state = "done" if data.get("status") in {"done", "completed"} else "failed"
        call.ended_at = call.ended_at or datetime.now(UTC)
        if call.outcome is None:
            metadata = data.get("metadata") or {}
            termination = str(metadata.get("termination_reason", "")).lower()
            if "no_answer" in termination or "no answer" in termination:
                call.outcome = "no_answer"
            elif "voicemail" in termination:
                call.outcome = "voicemail"
            elif call.state == "failed":
                call.outcome = "failed"
        duration = data.get("call_duration_secs")
        if isinstance(duration, (int, float)):
            call.duration_s = int(duration)
        transcript = data.get("transcript")
        if isinstance(transcript, list):
            transcript_text = " ".join(
                str(turn.get("message", "")) for turn in transcript if isinstance(turn, dict)
            )
            call.transcript_redacted = redact(transcript_text)
            call.recording_expires_at = datetime.now(UTC) + timedelta(days=RETENTION_DAYS)
        # Preserve a structured outcome already captured through record_outcome.
        session.commit()
        campaign = session.get(Campaign, call.campaign_id)
        active = session.scalar(select(func.count()).select_from(Call).where(
            Call.campaign_id == call.campaign_id,
            Call.state.in_(["queued", "dialing"]),
        ))
        if campaign and not active:
            campaign.status = "done"
            session.commit()
    return {"ok": True}


async def process_queue(campaign_id: str) -> None:
    semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT", "10")))

    async def process(call_id: str) -> None:
        async with semaphore:
            with Session(engine) as session:
                call = session.get(Call, call_id)
                if call is None or call.state != "queued":
                    return
                if call.contact.opted_out:
                    call.state = "failed"
                    call.outcome = "optout"
                    call.ended_at = datetime.now(UTC)
                    session.commit()
                    return
                call.state = "dialing"
                call.started_at = datetime.now(UTC)
                session.commit()
                if PROVIDER_MODE == "elevenlabs":
                    contact = call.contact
                    campaign = session.get(Campaign, call.campaign_id)
                    script = session.scalar(select(Script).where(
                        Script.campaign_id == call.campaign_id,
                        Script.language == contact.language,
                    ))
                    if campaign is None or script is None:
                        call.state = "failed"
                        call.outcome = "failed"
                        call.ended_at = datetime.now(UTC)
                        session.commit()
                        return
                    fields = json.loads(campaign.fields)
                    try:
                        call.conversation_id = await PROVIDER.start_call(CallRequest(
                            call_id=uuid.UUID(call.id),
                            to_e164=reveal(contact.phone_enc),
                            language=contact.language,
                            first_message=script.first_message,
                            voicemail_message=script.voicemail_message,
                            key_points=script.key_points,
                            dynamic_variables={
                                "contact_name": reveal(contact.name_enc),
                                "language": contact.language,
                                **{key: str(value) for key, value in fields.items()},
                                "call_id": call.id,
                            },
                        ))
                        session.commit()
                    except Exception:
                        call.state = "failed"
                        call.outcome = "failed"
                        call.ended_at = datetime.now(UTC)
                        session.commit()
                    return
                simulation = await PROVIDER.simulate(call.attempt_no, int(call.id[-8:], 16))
                call.outcome = simulation.outcome
                outcome = simulation.outcome
                call.state = "done"
                call.input_mode = simulation.input_mode
                call.duration_s = simulation.duration_s
                call.transcript_redacted = redact(f"Caller response recorded as {outcome}.")
                call.recording_expires_at = datetime.now(UTC) + timedelta(days=RETENTION_DAYS)
                call.ended_at = datetime.now(UTC)
                if outcome == "optout":
                    call.contact.opted_out = True
                session.commit()

    with Session(engine) as session:
        queued = list(session.scalars(select(Call.id).where(Call.campaign_id == campaign_id, Call.state == "queued")))
    await asyncio.gather(*(process(call_id) for call_id in queued))
    with Session(engine) as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign:
            active = session.scalar(select(func.count()).select_from(Call).where(Call.campaign_id == campaign_id, Call.state.in_(["queued", "dialing"])))
            if not active:
                campaign.status = "done"
                session.commit()


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "provider_mode": PROVIDER_MODE}


@app.get("/templates", tags=["templates"])
def list_templates() -> list[TemplateSpec]:
    return list(TEMPLATES.values())


@app.post("/campaigns", status_code=201, tags=["campaigns"])
async def create_campaign(
    csv_file: Annotated[UploadFile, File(alias="csv")],
    template_id: Annotated[str, Form()],
    fields: Annotated[str, Form()],
    languages: Annotated[str, Form()],
) -> dict[str, object]:
    template = TEMPLATES.get(template_id)
    if not template:
        raise HTTPException(422, "Unknown template")
    try:
        parsed_fields = json.loads(fields)
        parsed_languages = json.loads(languages)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Fields and languages must be JSON") from exc
    if not isinstance(parsed_fields, dict) or not all(isinstance(value, (str, int, float)) for value in parsed_fields.values()):
        raise HTTPException(422, "Fields must be a JSON object of text values")
    field_values = {str(key): str(value).strip() for key, value in parsed_fields.items()}
    if not isinstance(parsed_languages, list) or not all(isinstance(language, str) for language in parsed_languages):
        raise HTTPException(422, "Languages must be a JSON array")
    requested_languages: list[str] = parsed_languages
    if len(set(requested_languages)) != len(requested_languages):
        raise HTTPException(422, "Languages cannot contain duplicates")
    required = set(template["fields"])
    missing = required - set(field_values)
    if missing or any(not str(field_values[key]).strip() for key in required):
        raise HTTPException(422, f"Missing required fields: {', '.join(sorted(missing or required))}")
    if not requested_languages or not set(requested_languages) <= LANGUAGES:
        raise HTTPException(422, "Choose one or more supported languages: en, hi, ml")
    try:
        raw = (await csv_file.read()).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "CSV must use UTF-8 encoding") from exc
    try:
        rows = list(csv.DictReader(io.StringIO(raw)))
    except csv.Error as exc:
        raise HTTPException(422, "Invalid CSV") from exc
    if not rows or not {"name", "phone", "language"} <= set(rows[0]):
        raise HTTPException(422, "CSV must have name, phone, language columns")
    normalized: list[tuple[str, str, str, str, str, bool]] = []
    seen_phone_hashes: set[str] = set()
    for line, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        phone = re.sub(r"[\s()-]", "", row.get("phone") or "")
        language = (row.get("language") or "").strip().lower()
        segment = (row.get("segment") or "General").strip()[:120] or "General"
        opted_out = (row.get("opted_out") or "").strip().lower() in {"1", "true", "yes"}
        if not name or not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
            raise HTTPException(422, f"Invalid name or E.164 phone at CSV row {line}")
        if language not in requested_languages:
            raise HTTPException(422, f"Unsupported or unselected language at CSV row {line}")
        digest = phone_hash(phone)
        if digest in seen_phone_hashes:
            raise HTTPException(422, f"Duplicate phone at CSV row {line}")
        seen_phone_hashes.add(digest)
        normalized.append((name, phone, digest, language, segment, opted_out))
    if not normalized:
        raise HTTPException(422, "CSV has no contacts")
    campaign = Campaign(
        id=str(uuid.uuid4()),
        name=str(field_values.get("topic") or field_values.get("clinic") or template["name"]),
        template_id=template_id,
        fields=to_json(field_values),
        languages=to_json(requested_languages),
    )
    with Session(engine) as session:
        session.add(campaign)
        for name, phone, digest, language, segment, opted_out in normalized:
            session.add(Contact(id=str(uuid.uuid4()), campaign_id=campaign.id, name_enc=seal(name), phone_enc=seal(phone), phone_hash=digest, language=language, segment=segment, opted_out=opted_out))
        for language in requested_languages:
            message, voicemail = script_copy(language, template_id, field_values)
            session.add(Script(id=str(uuid.uuid4()), campaign_id=campaign.id, language=language, first_message=message, voicemail_message=voicemail, key_points=json.dumps(field_values, ensure_ascii=False)))
        session.commit()
        session.refresh(campaign)
        return campaign_detail(campaign, session)


@app.get("/campaigns", tags=["campaigns"])
def get_campaigns() -> list[dict[str, object]]:
    with Session(engine) as session:
        campaigns = list(session.scalars(select(Campaign).order_by(Campaign.created_at.desc())))
        return [campaign_detail(campaign, session) for campaign in campaigns]


@app.get("/campaigns/{campaign_id}", tags=["campaigns"])
def get_campaign(campaign_id: str) -> dict[str, object]:
    with Session(engine) as session:
        campaign = session.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        return campaign_detail(campaign, session)


@app.patch("/campaigns/{campaign_id}/scripts/{language}", tags=["campaigns"])
def update_script(campaign_id: str, language: str, body: ScriptUpdate) -> dict[str, object]:
    with Session(engine) as session:
        script = session.scalar(select(Script).where(Script.campaign_id == campaign_id, Script.language == language))
        if not script:
            raise HTTPException(404, "Script not found")
        if script.campaign.status != "draft":
            raise HTTPException(409, "Scripts can only be edited while the campaign is a draft")
        script.first_message = body.first_message
        script.voicemail_message = body.voicemail_message
        script.key_points = body.key_points
        script.approved = False
        session.commit()
        return {"ok": True}


@app.post("/campaigns/{campaign_id}/approve", tags=["campaigns"])
def approve_campaign(campaign_id: str) -> dict[str, object]:
    with Session(engine) as session:
        campaign = session.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        for script in campaign.scripts:
            script.approved = True
        if not campaign.scripts:
            raise HTTPException(409, "Campaign has no scripts")
        campaign.status = "ready"
        session.commit()
        return campaign_detail(campaign, session)


@app.post("/campaigns/{campaign_id}/launch", tags=["campaigns"])
def launch_campaign(campaign_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
    with Session(engine) as session:
        campaign = session.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        if campaign.status not in {"ready", "done"}:
            raise HTTPException(409, "Approve the campaign before launching")
        if not all(script.approved for script in campaign.scripts):
            raise HTTPException(409, "Approve all scripts before launching")
        contacts = list(session.scalars(select(Contact).where(Contact.campaign_id == campaign_id, Contact.opted_out.is_(False))))
        for contact in contacts:
            if not session.scalar(select(Call.id).where(Call.contact_id == contact.id)):
                session.add(Call(id=str(uuid.uuid4()), campaign_id=campaign_id, contact_id=contact.id, attempt_no=1))
        campaign.status = "running"
        session.commit()
    background_tasks.add_task(process_queue, campaign_id)
    return {"ok": True, "status": "running", "provider_mode": PROVIDER_MODE}


@app.post("/campaigns/{campaign_id}/retry", tags=["campaigns"])
def retry_campaign(campaign_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
    with Session(engine) as session:
        campaign = session.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        if campaign.status == "running":
            raise HTTPException(409, "Wait for the current simulation to finish")
        if campaign.status not in {"ready", "done"}:
            raise HTTPException(409, "Approve the campaign before retrying")
        contacts = list(session.scalars(select(Contact).where(Contact.campaign_id == campaign_id, Contact.opted_out.is_(False))))
        queued = 0
        for contact in contacts:
            calls = list(session.scalars(select(Call).where(Call.contact_id == contact.id).order_by(Call.attempt_no.desc())))
            if not calls:
                continue
            latest = calls[0]
            if latest.outcome not in {"no_answer", "voicemail", "failed"} or latest.attempt_no >= MAX_ATTEMPTS:
                continue
            session.add(Call(id=str(uuid.uuid4()), campaign_id=campaign_id, contact_id=contact.id, attempt_no=latest.attempt_no + 1))
            queued += 1
        if not queued:
            return {"ok": True, "queued": 0, "message": "No eligible non-responders to retry"}
        campaign.status = "running"
        session.commit()
    background_tasks.add_task(process_queue, campaign_id)
    return {"ok": True, "queued": queued, "status": "running"}


@app.get("/campaigns/{campaign_id}/summary", tags=["campaigns"])
def get_summary(campaign_id: str) -> dict[str, object]:
    with Session(engine) as session:
        if not session.get(Campaign, campaign_id):
            raise HTTPException(404, "Campaign not found")
        return campaign_summary(campaign_id, session)


@app.get("/campaigns/{campaign_id}/calls", tags=["campaigns"])
def get_calls(campaign_id: str) -> list[dict[str, object]]:
    with Session(engine) as session:
        if not session.get(Campaign, campaign_id):
            raise HTTPException(404, "Campaign not found")
        calls = list(session.scalars(select(Call).where(Call.campaign_id == campaign_id).order_by(Call.started_at.desc().nullslast(), Call.attempt_no.desc())))
        return [
            {
                "id": call.id,
                "name": reveal(call.contact.name_enc)[:1] + "•••",
                "phone": mask_phone(reveal(call.contact.phone_enc)),
                "language": call.contact.language,
                "segment": call.contact.segment,
                "attempt": call.attempt_no,
                "state": call.state,
                "outcome": call.outcome,
                "input_mode": call.input_mode,
                "duration_s": call.duration_s,
                "transcript_redacted": call.transcript_redacted,
            }
            for call in calls
        ]


@app.delete("/campaigns/{campaign_id}", status_code=204, tags=["campaigns"])
def delete_campaign(campaign_id: str) -> None:
    with Session(engine) as session:
        campaign = session.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        session.delete(campaign)
        session.commit()
