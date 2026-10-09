import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
import re
import uuid
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Literal, TypedDict
from zoneinfo import ZoneInfo

import httpx
from cryptography.fernet import Fernet
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from app.providers import CallRequest, ElevenLabsProvider, MockProvider, VoiceProvider
from app.services.scripts import (
    GeneratedScript,
    HuggingFaceScriptGenerator,
    LANGUAGE_NAMES,
    MockScriptGenerator,
    ScriptGenerationError,
    ScriptGenerator,
)
from app.services.rsvp_simulation import (
    SCENARIOS as RSVP_DEMO_CASES,
    ElevenLabsRsvpSimulation,
    ElevenLabsSimulationError,
)

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
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
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
    exact_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_mode: Mapped[str | None] = mapped_column(String(12), nullable=True)
    party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    callback_time: Mapped[str | None] = mapped_column(String(160), nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    recording_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    simulation_test_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    simulation_invocation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact: Mapped[Contact] = relationship(back_populates="calls")


class WebhookReceipt(Base):
    __tablename__ = "webhook_receipts"

    conversation_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class DemoRsvpCall(Base):
    __tablename__ = "demo_rsvp_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    scenario: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str] = mapped_column(String(20))
    exact_response: Mapped[str] = mapped_column(Text)
    transcript: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(40), default="scripted")
    extraction_status: Mapped[str] = mapped_column(String(40), default="captured")
    test_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    invocation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class DemoRsvpRun(Base):
    __tablename__ = "demo_rsvp_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    invocation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DemoRsvpTest(Base):
    __tablename__ = "demo_rsvp_tests"

    scenario: Mapped[str] = mapped_column(String(20), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(120))
    test_id: Mapped[str] = mapped_column(String(120))


class DemoRsvpAgent(Base):
    __tablename__ = "demo_rsvp_agents"

    source_agent_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    rsvp_agent_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    tool_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


Base.metadata.create_all(engine)
# create_all does not add columns to databases created by earlier versions.
with engine.begin() as connection:
    if DATABASE_URL.startswith("sqlite"):
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(calls)")}
        if "conversation_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE calls ADD COLUMN conversation_id VARCHAR(120)")
        if "simulation_test_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE calls ADD COLUMN simulation_test_id VARCHAR(120)")
        if "simulation_invocation_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE calls ADD COLUMN simulation_invocation_id VARCHAR(120)")
        if "exact_response" not in columns:
            connection.exec_driver_sql("ALTER TABLE calls ADD COLUMN exact_response TEXT")
        if "party_size" not in columns:
            connection.exec_driver_sql("ALTER TABLE calls ADD COLUMN party_size INTEGER")
        if "callback_time" not in columns:
            connection.exec_driver_sql("ALTER TABLE calls ADD COLUMN callback_time VARCHAR(160)")
        contact_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(contacts)")}
        if "external_id" not in contact_columns:
            connection.exec_driver_sql("ALTER TABLE contacts ADD COLUMN external_id VARCHAR(120)")
        demo_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(demo_rsvp_calls)")}
        if demo_columns:
            if "provider" not in demo_columns:
                connection.exec_driver_sql("ALTER TABLE demo_rsvp_calls ADD COLUMN provider VARCHAR(40) NOT NULL DEFAULT 'scripted'")
            if "extraction_status" not in demo_columns:
                connection.exec_driver_sql("ALTER TABLE demo_rsvp_calls ADD COLUMN extraction_status VARCHAR(40) NOT NULL DEFAULT 'captured'")
            if "test_id" not in demo_columns:
                connection.exec_driver_sql("ALTER TABLE demo_rsvp_calls ADD COLUMN test_id VARCHAR(120)")
            if "invocation_id" not in demo_columns:
                connection.exec_driver_sql("ALTER TABLE demo_rsvp_calls ADD COLUMN invocation_id VARCHAR(120)")
        agent_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(demo_rsvp_agents)")}
        if agent_columns:
            if "rsvp_agent_id" not in agent_columns:
                connection.exec_driver_sql("ALTER TABLE demo_rsvp_agents ADD COLUMN rsvp_agent_id VARCHAR(120)")
            if "tool_id" not in agent_columns:
                connection.exec_driver_sql("ALTER TABLE demo_rsvp_agents ADD COLUMN tool_id VARCHAR(120)")
app = FastAPI(title="Swaram API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3010",
        "http://127.0.0.1:3010",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Tool-Secret"],
)

LANGUAGES = set(LANGUAGE_NAMES)
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))
OUTCOMES = ["confirmed", "declined", "maybe", "callback", "optout", "other", "no_answer", "voicemail", "failed"]


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
QUEUE_TASKS: set[asyncio.Task[None]] = set()
MAX_CONCURRENT = max(1, int(os.getenv("MAX_CONCURRENT", "2")))
SIMULATION_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT)
PROVIDER_MODE = os.getenv("PROVIDER_MODE", "mock").lower()
SCRIPT_PROVIDER_MODE = os.getenv("SCRIPT_PROVIDER_MODE", "mock").lower()
if SCRIPT_PROVIDER_MODE == "mock":
    SCRIPT_GENERATOR: ScriptGenerator = MockScriptGenerator()
elif SCRIPT_PROVIDER_MODE == "huggingface":
    script_required_env = ("HF_TOKEN", "HF_MODEL")
    script_missing_env = [key for key in script_required_env if not os.getenv(key)]
    if script_missing_env:
        raise RuntimeError(
            f"SCRIPT_PROVIDER_MODE=huggingface requires: {', '.join(script_missing_env)}"
        )
    SCRIPT_GENERATOR = HuggingFaceScriptGenerator(
        token=os.environ["HF_TOKEN"],
        model=os.environ["HF_MODEL"],
    )
else:
    raise RuntimeError("SCRIPT_PROVIDER_MODE must be 'mock' or 'huggingface'")
if PROVIDER_MODE == "elevenlabs":
    TELEPHONY_KIND = os.getenv("TELEPHONY_KIND", "twilio").lower()
    if TELEPHONY_KIND not in {"twilio", "exotel"}:
        raise RuntimeError("TELEPHONY_KIND must be 'twilio' or 'exotel'")
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
        telephony_kind=TELEPHONY_KIND,
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
        running_campaign_ids = list(session.scalars(
            select(Campaign.id).where(Campaign.status == "running")
        ))
    for campaign_id in running_campaign_ids:
        task = asyncio.get_running_loop().create_task(process_queue(campaign_id))
        QUEUE_TASKS.add(task)
        task.add_done_callback(QUEUE_TASKS.discard)
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
    for task in QUEUE_TASKS:
        task.cancel()
    if QUEUE_TASKS:
        await asyncio.gather(*QUEUE_TASKS, return_exceptions=True)
        QUEUE_TASKS.clear()
    if PURGE_TASK and not PURGE_TASK.done():
        PURGE_TASK.cancel()
        PURGE_TASK = None
    close_provider = getattr(PROVIDER, "close", None)
    if close_provider is not None:
        await close_provider()
    await SCRIPT_GENERATOR.close()


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


def call_window_open(now: datetime | None = None) -> bool:
    configured = os.getenv("CALL_WINDOW", "09:00-20:00")
    try:
        start_text, end_text = configured.split("-", maxsplit=1)
        start = time.fromisoformat(start_text)
        end = time.fromisoformat(end_text)
    except ValueError:
        return False
    if start == end:
        return False
    local_now = (now or datetime.now(ZoneInfo("Asia/Kolkata"))).astimezone(
        ZoneInfo("Asia/Kolkata")
    ).time()
    if start < end:
        return start <= local_now < end
    return local_now >= start or local_now < end


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
    retryable = sum(
        1 for contact in contacts
        if not contact.opted_out
        and contact.id in latest
        and latest[contact.id].outcome in {"no_answer", "voicemail", "failed"}
        and latest[contact.id].attempt_no < MAX_ATTEMPTS
    )
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
        "retryable_contacts": retryable,
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


class HumanOutcomeUpdate(BaseModel):
    outcome: Literal[
        "confirmed", "declined", "maybe", "callback", "optout", "other",
        "no_answer", "voicemail", "failed",
    ]


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
    event_type = event.get("type")
    if event_type not in {"post_call_transcription", "call_initiation_failure"}:
        return {"ok": True}
    data = event.get("data") or {}
    if not isinstance(data, dict):
        raise HTTPException(400, "Webhook data must be a JSON object")
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        raise HTTPException(422, "Webhook missing conversation_id")
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    try:
        with Session(engine) as session:
            call = session.scalar(select(Call).where(Call.conversation_id == conversation_id))
            if call is None:
                # Acknowledge safely: delivery may arrive before transaction commit or
                # for a call removed by retention/deletion.
                return {"ok": True}
            if session.get(WebhookReceipt, (conversation_id, event_type)):
                return {"ok": True}
            session.add(WebhookReceipt(conversation_id=conversation_id, event_type=event_type))
            session.flush()
            if event_type == "call_initiation_failure":
                failure_reason = str(data.get("failure_reason", "unknown")).lower().replace("_", "-")
                call.state = "failed"
                call.outcome = "no_answer" if failure_reason in {"no-answer", "busy"} else "failed"
                call.ended_at = call.ended_at or datetime.now(UTC)
            else:
                call.state = "done" if data.get("status") in {"done", "completed"} else "failed"
                call.ended_at = call.ended_at or datetime.now(UTC)
                if call.outcome is None:
                    termination = str(metadata.get("termination_reason", "")).lower()
                    if "no_answer" in termination or "no answer" in termination:
                        call.outcome = "no_answer"
                    elif "voicemail" in termination:
                        call.outcome = "voicemail"
                    else:
                        call.outcome = "failed"
                duration = metadata.get("call_duration_secs", data.get("call_duration_secs"))
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
            campaign_id = call.campaign_id
            session.flush()
            active = session.scalar(select(func.count()).select_from(Call).where(
                Call.campaign_id == campaign_id,
                Call.state.in_(["queued", "dialing"]),
            ))
            if active == 0:
                campaign = session.get(Campaign, campaign_id)
                if campaign:
                    campaign.status = "done"
            session.commit()
    except IntegrityError:
        # Concurrent retries race on the receipt primary key; the first delivery wins.
        return {"ok": True}
    return {"ok": True}


async def process_elevenlabs_simulation_queue(campaign_id: str) -> None:
    """Run one natural ElevenLabs Agent Testing conversation per contact; never place phone calls."""
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    source_agent_id = os.getenv("ELEVENLABS_AGENT_ID", "").strip()
    if not api_key or not source_agent_id:
        detail = "Set ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID to run phone-free campaign simulations."
        with Session(engine) as session:
            for call in session.scalars(select(Call).where(Call.campaign_id == campaign_id, Call.state == "queued")):
                call.state, call.outcome, call.ended_at = "failed", "failed", datetime.now(UTC)
                call.transcript_redacted = detail
            campaign = session.get(Campaign, campaign_id)
            if campaign:
                campaign.status = "done"
            session.commit()
        return

    simulator = ElevenLabsRsvpSimulation(api_key)
    try:
        source_agent = await simulator.get_agent(source_agent_id)
        with Session(engine) as session:
            campaign = session.get(Campaign, campaign_id)
            campaign_languages = json.loads(campaign.languages) if campaign else []
            cached_agents = list(session.scalars(select(DemoRsvpAgent).where(
                DemoRsvpAgent.source_agent_id.like(f"campaign:{source_agent_id}:%")
            )))
        tool_id = next((item.tool_id for item in cached_agents if item.tool_id), None)
        if not tool_id:
            tool_id = await simulator.create_outcome_tool()
        agents_by_language: dict[str, str] = {}
        cache_by_key = {item.source_agent_id: item for item in cached_agents}
        for language in campaign_languages:
            cache_key = f"campaign:{source_agent_id}:{language}"
            saved_agent = cache_by_key.get(cache_key)
            agent_id = saved_agent.rsvp_agent_id if saved_agent else None
            if not agent_id:
                agent_id = await simulator.create_campaign_agent(source_agent, tool_id, language)
            agents_by_language[language] = agent_id
            with Session(engine) as session:
                saved_agent = session.get(DemoRsvpAgent, cache_key)
                if saved_agent is None:
                    session.add(DemoRsvpAgent(source_agent_id=cache_key, rsvp_agent_id=agent_id, tool_id=tool_id))
                else:
                    saved_agent.rsvp_agent_id, saved_agent.tool_id = agent_id, tool_id
                session.commit()

        while True:
            with Session(engine) as session:
                queued_ids = list(session.scalars(
                    select(Call.id).where(Call.campaign_id == campaign_id, Call.state == "queued")
                    .order_by(Call.attempt_no, Call.id).limit(MAX_CONCURRENT)
                ))
                if not queued_ids:
                    active = session.scalar(select(func.count()).select_from(Call).where(
                        Call.campaign_id == campaign_id, Call.state.in_(["queued", "dialing"])
                    )) or 0
                    campaign = session.get(Campaign, campaign_id)
                    if campaign is not None and active == 0:
                        campaign.status = "done"
                        session.commit()
                    break
                # Atomic state transition is the shared claim: concurrent workers cannot take the same contact.
                claimed: list[str] = []
                for call_id in queued_ids:
                    result = session.execute(
                        update(Call).where(Call.id == call_id, Call.state == "queued")
                        .values(state="dialing", started_at=datetime.now(UTC))
                    )
                    if result.rowcount:
                        claimed.append(call_id)
                session.commit()

            async def simulate_one(call_id: str) -> None:
                async with SIMULATION_SEMAPHORE:
                    with Session(engine) as session:
                        call = session.get(Call, call_id)
                        if call is None or call.state != "dialing":
                            return
                        contact = call.contact
                        campaign = session.get(Campaign, campaign_id)
                        script = session.scalar(select(Script).where(
                            Script.campaign_id == campaign_id, Script.language == contact.language
                        ))
                        if campaign is None or script is None:
                            call.state, call.outcome = "failed", "failed"
                            call.transcript_redacted = "No approved language script was found for this contact."
                            call.ended_at = datetime.now(UTC)
                            session.commit()
                            return
                        name = reveal(contact.name_enc)
                        user_id = contact.external_id or contact.id[:8]
                        language = contact.language
                        language_name = LANGUAGE_NAMES.get(language, language)
                        fields = json.loads(campaign.fields)
                        context = "; ".join(f"{key}: {value}" for key, value in fields.items())
                        opening = script.first_message
                        if "{{contact_name}}" not in opening:
                            opening = f"Hi {name}, {opening[0].lower() + opening[1:] if opening else ''}"
                    try:
                        test_id = await simulator.create_contact_test(
                            user_id=user_id, name=name, language=language,
                            language_name=language_name, event_context=context,
                            opening_message=opening, tool_id=tool_id,
                        )
                        invocation_id, result = await simulator.run_test(agents_by_language[language], test_id, user_id)
                        outcome = str(result.get("outcome") or "other")
                        if outcome not in OUTCOMES:
                            outcome = "other"
                        transcript = redact(str(result.get("transcript") or ""))
                        exact_response = redact(str(result.get("exact_response") or ""))
                        with Session(engine) as session:
                            call = session.get(Call, call_id)
                            if call is None:
                                return
                            call.simulation_test_id = test_id
                            call.simulation_invocation_id = invocation_id
                            call.input_mode = "elevenlabs"
                            call.outcome = outcome
                            call.exact_response = exact_response or None
                            call.transcript_redacted = (
                                f"Participant's exact response: {exact_response}\n\n{transcript}"
                                if exact_response else transcript or "Simulation ended without a captured transcript."
                            )
                            call.state = "done"
                            call.ended_at = datetime.now(UTC)
                            call.recording_expires_at = datetime.now(UTC) + timedelta(days=RETENTION_DAYS)
                            if outcome == "optout":
                                call.contact.opted_out = True
                            session.commit()
                    except Exception as exc:
                        with Session(engine) as session:
                            call = session.get(Call, call_id)
                            if call is not None and call.state == "dialing":
                                call.state, call.outcome = "failed", "failed"
                                call.transcript_redacted = redact(str(exc))[:2000]
                                call.ended_at = datetime.now(UTC)
                                session.commit()

            await asyncio.gather(*(simulate_one(call_id) for call_id in claimed))
    except Exception as exc:
        with Session(engine) as session:
            for call in session.scalars(select(Call).where(Call.campaign_id == campaign_id, Call.state.in_(["queued", "dialing"]))):
                call.state, call.outcome = "failed", "failed"
                call.transcript_redacted = redact(str(exc))[:2000]
                call.ended_at = datetime.now(UTC)
            campaign = session.get(Campaign, campaign_id)
            if campaign:
                campaign.status = "done"
            session.commit()
    finally:
        await simulator.close()


async def process_queue(campaign_id: str) -> None:
    if PROVIDER_MODE == "mock":
        await process_elevenlabs_simulation_queue(campaign_id)
        return
    max_concurrent = MAX_CONCURRENT
    semaphore = asyncio.Semaphore(max_concurrent)

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

    async def reconcile(call_id: str) -> None:
        with Session(engine) as session:
            call = session.get(Call, call_id)
            if call is None or call.state != "dialing" or not call.conversation_id:
                return
            conversation_id = call.conversation_id
        try:
            record = await PROVIDER.get_conversation(conversation_id)
            outcome = record.outcome if record.outcome in OUTCOMES else None
            status = record.status.lower().replace("-", "_")
            if status in {"initiated", "in_progress", "processing", "ringing"}:
                with Session(engine) as session:
                    call = session.get(Call, call_id)
                    if call is not None and call.state == "dialing":
                        call.started_at = datetime.now(UTC)
                        session.commit()
                return
            with Session(engine) as session:
                call = session.get(Call, call_id)
                if call is None or call.state != "dialing":
                    return
                call.state = "done" if status in {"done", "completed"} else "failed"
                call.outcome = outcome or "failed"
                call.duration_s = record.duration_s
                if record.transcript:
                    call.transcript_redacted = redact(record.transcript)
                    call.recording_expires_at = datetime.now(UTC) + timedelta(days=RETENTION_DAYS)
                call.ended_at = datetime.now(UTC)
                session.commit()
        except Exception:
            with Session(engine) as session:
                call = session.get(Call, call_id)
                if call is not None and call.state == "dialing":
                    call.state = "failed"
                    call.outcome = "failed"
                    call.ended_at = datetime.now(UTC)
                    session.commit()

    timeout_s = max(1, int(os.getenv("CALL_TIMEOUT_S", "90")))
    while True:
        with Session(engine) as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                return
            dialing = list(session.scalars(select(Call).where(
                Call.campaign_id == campaign_id,
                Call.state == "dialing",
            )))
            stale = [
                call.id for call in dialing
                if call.started_at is not None
                and (datetime.now(UTC) - as_utc(call.started_at)).total_seconds() >= timeout_s
            ]

        for call_id in stale:
            await reconcile(call_id)

        with Session(engine) as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                return
            queued = list(session.scalars(select(Call.id).where(
                Call.campaign_id == campaign_id,
                Call.state == "queued",
            )))
            dialing_count = session.scalar(select(func.count()).select_from(Call).where(
                Call.campaign_id == campaign_id,
                Call.state == "dialing",
            )) or 0
            if not queued and not dialing_count:
                campaign.status = "done"
                session.commit()
                return

        can_dial = PROVIDER_MODE != "elevenlabs" or call_window_open()
        available_slots = max(0, max_concurrent - dialing_count)
        if queued and can_dial and available_slots:
            batch = queued[:available_slots]
            await asyncio.gather(*(process(call_id) for call_id in batch))
        await asyncio.sleep(2)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "provider_mode": PROVIDER_MODE,
        "script_provider_mode": SCRIPT_PROVIDER_MODE,
    }


def require_supervisor_token(request: Request, environment_key: str) -> None:
    configured = os.getenv(environment_key, "")
    supplied = request.headers.get("Authorization", "")
    if not configured:
        raise HTTPException(503, "Supervisor access is not configured")
    expected = f"Bearer {configured}"
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(401, "Invalid supervisor credentials")


@app.get("/supervision/snapshot", tags=["supervision"])
def supervisor_snapshot(request: Request) -> dict[str, object]:
    require_supervisor_token(request, "SUPERVISOR_READ_TOKEN")
    with Session(engine) as session:
        campaigns = list(session.scalars(select(Campaign).order_by(Campaign.created_at)))
        snapshot: list[dict[str, object]] = []
        for campaign in campaigns:
            contacts = list(session.scalars(select(Contact).where(Contact.campaign_id == campaign.id)))
            scripts = list(session.scalars(select(Script).where(Script.campaign_id == campaign.id)))
            calls = list(session.scalars(select(Call).where(Call.campaign_id == campaign.id)))
            snapshot.append({
                "id": campaign.id,
                "name": campaign.name,
                "template_id": campaign.template_id,
                "status": campaign.status,
                "created_at": campaign.created_at.isoformat(),
                "languages": json.loads(campaign.languages),
                "scripts": [
                    {"language": script.language, "approved": script.approved}
                    for script in scripts
                ],
                "contacts": [
                    {
                        "ref": contact.id,
                        "language": contact.language,
                        "segment": contact.segment,
                        "opted_out": contact.opted_out,
                    }
                    for contact in contacts
                ],
                "calls": [
                    {
                        "id": call.id,
                        "contact_ref": call.contact_id,
                        "attempt": call.attempt_no,
                        "state": call.state,
                        "outcome": call.outcome,
                        "duration_s": call.duration_s,
                        "started_at": call.started_at.isoformat() if call.started_at else None,
                        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
                    }
                    for call in calls
                ],
            })
    return {"generated_at": datetime.now(UTC).isoformat(), "campaigns": snapshot}


def demo_call_data(call: DemoRsvpCall) -> dict[str, object]:
    return {
        "id": call.id,
        "batch_id": call.batch_id,
        "scenario": call.scenario,
        "outcome": call.outcome,
        "exact_response": call.exact_response,
        "transcript": call.transcript,
        "provider": call.provider,
        "extraction_status": call.extraction_status,
        "test_id": call.test_id,
        "invocation_id": call.invocation_id,
        "created_at": as_utc(call.created_at).isoformat(),
    }


async def process_rsvp_demo_run(run_id: str, agent_id: str, api_key: str) -> None:
    with Session(engine) as session:
        run = session.get(DemoRsvpRun, run_id)
        if run is None:
            return
        run.status = "running"
        session.commit()

    simulator = ElevenLabsRsvpSimulation(api_key)
    try:
        with Session(engine) as session:
            saved_agent = session.get(DemoRsvpAgent, agent_id)
            effective_agent_id = saved_agent.rsvp_agent_id if saved_agent else None
            tool_id = saved_agent.tool_id if saved_agent else None
        if tool_id is None:
            tool_id = await simulator.create_outcome_tool()
            with Session(engine) as session:
                saved_agent = session.get(DemoRsvpAgent, agent_id)
                if saved_agent is None:
                    saved_agent = DemoRsvpAgent(
                        source_agent_id=agent_id,
                        rsvp_agent_id=None,
                        tool_id=tool_id,
                        created_at=datetime.now(UTC),
                    )
                    session.add(saved_agent)
                else:
                    saved_agent.tool_id = tool_id
                    saved_agent.rsvp_agent_id = None
                session.commit()
        if effective_agent_id is None:
            source_agent = await simulator.get_agent(agent_id)
            effective_agent_id = (
                agent_id if simulator.is_rsvp_agent(source_agent)
                else await simulator.create_rsvp_agent(source_agent, tool_id)
            )
            if effective_agent_id != agent_id:
                with Session(engine) as session:
                    saved_agent = session.get(DemoRsvpAgent, agent_id)
                    if saved_agent is not None:
                        saved_agent.rsvp_agent_id = effective_agent_id
                    else:
                        session.add(DemoRsvpAgent(
                            source_agent_id=agent_id,
                            rsvp_agent_id=effective_agent_id,
                            tool_id=tool_id,
                            created_at=datetime.now(UTC),
                        ))
                    session.commit()
        with Session(engine) as session:
            existing = {
                item.scenario: item.test_id
                for item in session.scalars(
                    select(DemoRsvpTest).where(DemoRsvpTest.agent_id == effective_agent_id)
                )
            }
        test_ids = await simulator.ensure_tests(existing, tool_id)
        with Session(engine) as session:
            for scenario in RSVP_DEMO_CASES:
                test = session.get(DemoRsvpTest, scenario["key"])
                if test is None:
                    session.add(DemoRsvpTest(
                        scenario=scenario["key"],
                        agent_id=effective_agent_id,
                        test_id=test_ids[scenario["key"]],
                    ))
                else:
                    test.agent_id = effective_agent_id
                    test.test_id = test_ids[scenario["key"]]
            session.commit()

        invocation_id, results = await simulator.run_tests(effective_agent_id, test_ids)
        missing_outcomes = [
            item["scenario"] for item in results if item["extraction_status"] != "captured"
        ]
        created_at = datetime.now(UTC)
        with Session(engine) as session:
            for result in results:
                response_text = redact(str(result["exact_response"]))
                transcript = redact(str(result["transcript"]))
                session.add(DemoRsvpCall(
                    id=str(uuid.uuid4()),
                    batch_id=run_id,
                    scenario=str(result["scenario"]),
                    outcome=str(result["outcome"]),
                    exact_response=response_text,
                    transcript=transcript,
                    provider="elevenlabs_simulation",
                    extraction_status=str(result["extraction_status"]),
                    test_id=str(result["test_id"]) if result.get("test_id") else None,
                    invocation_id=invocation_id,
                    created_at=created_at,
                ))
            run = session.get(DemoRsvpRun, run_id)
            if run is not None:
                run.invocation_id = invocation_id
                run.status = "failed" if missing_outcomes else "completed"
                if missing_outcomes:
                    run.error = (
                        "ElevenLabs completed the conversation but did not call record_outcome "
                        "for: " + ", ".join(missing_outcomes) + ". Transcript saved for review."
                    )
                run.finished_at = created_at
            session.commit()
    except ElevenLabsSimulationError as exc:
        with Session(engine) as session:
            run = session.get(DemoRsvpRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = str(exc)
                run.finished_at = datetime.now(UTC)
                session.commit()
    except httpx.HTTPError:
        with Session(engine) as session:
            run = session.get(DemoRsvpRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = "Could not reach ElevenLabs. Check the API connection and try again."
                run.finished_at = datetime.now(UTC)
                session.commit()
    except Exception:
        with Session(engine) as session:
            run = session.get(DemoRsvpRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = "The ElevenLabs simulation failed while saving its result. Check the API logs."
                run.finished_at = datetime.now(UTC)
                session.commit()
    finally:
        await simulator.close()


@app.post("/demo/rsvp/runs", status_code=202, tags=["demo"])
def start_rsvp_demo(background_tasks: BackgroundTasks) -> dict[str, object]:
    """Start three ElevenLabs agent-testing simulations; this endpoint never places calls."""
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "").strip()
    if not api_key or not agent_id:
        raise HTTPException(
            503,
            "Set ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID in the API environment to run this demo.",
        )
    run_id = str(uuid.uuid4())
    run = DemoRsvpRun(id=run_id, status="queued", created_at=datetime.now(UTC))
    with Session(engine) as session:
        session.add(run)
        session.commit()
    background_tasks.add_task(process_rsvp_demo_run, run_id, agent_id, api_key)
    return {"run_id": run_id, "status": "queued", "provider": "elevenlabs_simulation"}


@app.get("/demo/rsvp/runs/{run_id}", tags=["demo"])
def get_rsvp_demo_run(run_id: str) -> dict[str, object]:
    with Session(engine) as session:
        run = session.get(DemoRsvpRun, run_id)
        if run is None:
            raise HTTPException(404, "RSVP simulation run not found")
        calls = list(session.scalars(
            select(DemoRsvpCall).where(DemoRsvpCall.batch_id == run_id)
        ))
        order = {"yes": 0, "no": 1, "ambiguous": 2}
        calls.sort(key=lambda call: order.get(call.scenario, 99))
        return {
            "run_id": run.id,
            "status": run.status,
            "invocation_id": run.invocation_id,
            "error": run.error,
            "calls": [demo_call_data(call) for call in calls],
        }


@app.get("/demo/rsvp/calls", tags=["demo"])
def get_rsvp_demo_calls() -> list[dict[str, object]]:
    with Session(engine) as session:
        calls = list(session.scalars(
            select(DemoRsvpCall)
            .where(DemoRsvpCall.provider == "elevenlabs_simulation")
            .order_by(DemoRsvpCall.created_at.desc()).limit(300)
        ))
        return [demo_call_data(call) for call in calls]


@app.get("/demo/rsvp/calls.csv", tags=["demo"])
def export_rsvp_demo_calls() -> Response:
    with Session(engine) as session:
        calls = list(session.scalars(
            select(DemoRsvpCall)
            .where(DemoRsvpCall.provider == "elevenlabs_simulation")
            .order_by(DemoRsvpCall.created_at.desc())
        ))
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["call_id", "batch_id", "scenario", "outcome", "extraction_status", "provider", "exact_response", "transcript", "elevenlabs_test_id", "test_invocation_id", "created_at"])
    for call in calls:
        writer.writerow([
            call.id, call.batch_id, call.scenario, call.outcome, call.extraction_status, call.provider,
            call.exact_response, call.transcript, call.test_id, call.invocation_id,
            as_utc(call.created_at).isoformat(),
        ])
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="hackathon-rsvp-calls.csv"'},
    )


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
    unexpected = set(field_values) - required
    if unexpected:
        raise HTTPException(422, f"Unexpected template fields: {', '.join(sorted(unexpected))}")
    if missing or any(not str(field_values[key]).strip() for key in required):
        raise HTTPException(422, f"Missing required fields: {', '.join(sorted(missing or required))}")
    if not requested_languages or not set(requested_languages) <= LANGUAGES:
        supported = ", ".join(LANGUAGE_NAMES[code] for code in sorted(LANGUAGES))
        raise HTTPException(422, f"Choose one or more supported languages: {supported}")
    try:
        raw = (await csv_file.read()).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "CSV must use UTF-8 encoding") from exc
    try:
        rows = list(csv.DictReader(io.StringIO(raw)))
    except csv.Error as exc:
        raise HTTPException(422, "Invalid CSV") from exc
    if not rows or not {"name", "phone", "language"} <= set(rows[0]):
        raise HTTPException(422, "CSV must have name, phone, language columns; user_id is recommended")
    normalized: list[tuple[str, str, str, str, str, bool, str | None]] = []
    seen_phone_hashes: set[str] = set()
    seen_user_ids: set[str] = set()
    for line, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        phone = re.sub(r"[\s()-]", "", row.get("phone") or "")
        language = (row.get("language") or "").strip().lower()
        external_id = (row.get("user_id") or row.get("id") or "").strip()[:120] or None
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
        if external_id and external_id in seen_user_ids:
            raise HTTPException(422, f"Duplicate user_id at CSV row {line}")
        if external_id:
            seen_user_ids.add(external_id)
        normalized.append((name, phone, digest, language, segment, opted_out, external_id))
    if not normalized:
        raise HTTPException(422, "CSV has no contacts")
    try:
        generated = await asyncio.gather(*(
            SCRIPT_GENERATOR.generate(language, template_id, field_values)
            for language in requested_languages
        ))
    except ScriptGenerationError as exc:
        raise HTTPException(502, f"Script generation failed; campaign was not created: {exc}") from exc
    scripts_by_language: dict[str, GeneratedScript] = dict(
        zip(requested_languages, generated, strict=True)
    )
    campaign = Campaign(
        id=str(uuid.uuid4()),
        name=str(field_values.get("topic") or field_values.get("clinic") or template["name"]),
        template_id=template_id,
        fields=to_json(field_values),
        languages=to_json(requested_languages),
    )
    with Session(engine) as session:
        session.add(campaign)
        for name, phone, digest, language, segment, opted_out, external_id in normalized:
            session.add(Contact(id=str(uuid.uuid4()), campaign_id=campaign.id, external_id=external_id, name_enc=seal(name), phone_enc=seal(phone), phone_hash=digest, language=language, segment=segment, opted_out=opted_out))
        for language in requested_languages:
            draft = scripts_by_language[language]
            session.add(Script(
                id=str(uuid.uuid4()),
                campaign_id=campaign.id,
                language=language,
                first_message=draft.first_message,
                voicemail_message=draft.voicemail_message,
                key_points=draft.key_points,
            ))
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
        if campaign.status != "draft":
            raise HTTPException(409, "Only draft campaigns can be approved")
        expected_languages = set(json.loads(campaign.languages))
        if {script.language for script in campaign.scripts} != expected_languages:
            raise HTTPException(409, "A script is required for every campaign language")
        for script in campaign.scripts:
            script.approved = True
        if not campaign.scripts:
            raise HTTPException(409, "Campaign has no scripts")
        campaign.status = "ready"
        session.commit()
        return campaign_detail(campaign, session)


@app.post("/campaigns/{campaign_id}/launch", tags=["campaigns"])
def launch_campaign(campaign_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
    if PROVIDER_MODE == "mock" and not (
        os.getenv("ELEVENLABS_API_KEY", "").strip()
        and os.getenv("ELEVENLABS_AGENT_ID", "").strip()
    ):
        raise HTTPException(
            503,
            "Phone-free campaign runs use ElevenLabs Agent Testing. Set ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID in the API environment.",
        )
    with Session(engine) as session:
        campaign = session.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        if campaign.status != "ready":
            raise HTTPException(409, "Approve the draft before launching")
        if not all(script.approved for script in campaign.scripts):
            raise HTTPException(409, "Approve all scripts before launching")
        contacts = list(session.scalars(select(Contact).where(Contact.campaign_id == campaign_id, Contact.opted_out.is_(False))))
        for contact in contacts:
            if not session.scalar(select(Call.id).where(Call.contact_id == contact.id)):
                session.add(Call(id=str(uuid.uuid4()), campaign_id=campaign_id, contact_id=contact.id, attempt_no=1))
        campaign.status = "running"
        session.commit()
    background_tasks.add_task(process_queue, campaign_id)
    return {
        "ok": True,
        "status": "running",
        "provider_mode": "elevenlabs_simulation" if PROVIDER_MODE == "mock" else PROVIDER_MODE,
        "max_concurrent": MAX_CONCURRENT,
        "phone_calls_placed": False if PROVIDER_MODE == "mock" else None,
    }


@app.post("/campaigns/{campaign_id}/retry", tags=["campaigns"])
def retry_campaign(campaign_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
    with Session(engine) as session:
        campaign = session.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        if campaign.status != "done":
            raise HTTPException(409, "Wait for the campaign to finish before retrying")
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


@app.post("/supervision/campaigns/{campaign_id}/retry", tags=["supervision"])
def supervisor_retry_campaign(
    campaign_id: str, request: Request, background_tasks: BackgroundTasks
) -> dict[str, object]:
    if os.getenv("SUPERVISOR_AUTO_RETRY", "false").lower() != "true":
        raise HTTPException(403, "Automatic supervisor retries are disabled")
    require_supervisor_token(request, "SUPERVISOR_ACTION_TOKEN")
    return retry_campaign(campaign_id, background_tasks)


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
                "user_id": call.contact.external_id or call.contact.id[:8],
                "name": reveal(call.contact.name_enc)[:1] + "•••",
                "phone": mask_phone(reveal(call.contact.phone_enc)),
                "language": call.contact.language,
                "segment": call.contact.segment,
                "attempt": call.attempt_no,
                "state": call.state,
                "outcome": call.outcome,
                "input_mode": call.input_mode,
                "duration_s": call.duration_s,
                "callback_time": call.callback_time,
                "exact_response": call.exact_response,
                "transcript_redacted": call.transcript_redacted,
            }
            for call in calls
        ]


@app.get("/campaigns/{campaign_id}/calls.csv", tags=["campaigns"])
def export_campaign_calls(campaign_id: str) -> Response:
    with Session(engine) as session:
        if not session.get(Campaign, campaign_id):
            raise HTTPException(404, "Campaign not found")
        calls = list(session.scalars(
            select(Call).where(Call.campaign_id == campaign_id)
            .order_by(Call.contact_id, Call.attempt_no)
        ))
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow([
            "user_id", "name", "phone", "language", "segment", "attempt",
            "state", "outcome", "exact_response", "transcript", "callback_time", "mode",
        ])
        for call in calls:
            writer.writerow([
                call.contact.external_id or call.contact.id[:8],
                reveal(call.contact.name_enc),
                reveal(call.contact.phone_enc),
                call.contact.language,
                call.contact.segment,
                call.attempt_no,
                call.state,
                call.outcome or "",
                call.exact_response or "",
                call.transcript_redacted or "",
                call.callback_time or "",
                call.input_mode or "",
            ])
        return Response(
            content="\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="swaram-campaign-{campaign_id[:8]}-results.csv"'},
        )


@app.patch("/calls/{call_id}/outcome", tags=["supervision"])
def update_call_outcome(call_id: str, body: HumanOutcomeUpdate) -> dict[str, object]:
    with Session(engine) as session:
        call = session.get(Call, call_id)
        if call is None:
            raise HTTPException(404, "Call not found")
        if call.state not in {"done", "failed"}:
            raise HTTPException(409, "Only completed calls can be reviewed")
        if call.outcome == "optout" and body.outcome != "optout":
            raise HTTPException(409, "An opt-out outcome cannot be reversed")
        call.outcome = body.outcome
        if body.outcome == "optout":
            call.contact.opted_out = True
        session.commit()
        return {"ok": True, "outcome": call.outcome}


@app.delete("/campaigns/{campaign_id}", status_code=204, tags=["campaigns"])
def delete_campaign(campaign_id: str) -> None:
    with Session(engine) as session:
        campaign = session.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        conversation_ids = list(session.scalars(
            select(Call.conversation_id).where(
                Call.campaign_id == campaign_id,
                Call.conversation_id.is_not(None),
            )
        ))
        if conversation_ids:
            session.execute(delete(WebhookReceipt).where(
                WebhookReceipt.conversation_id.in_(conversation_ids)
            ))
        session.delete(campaign)
        session.commit()
