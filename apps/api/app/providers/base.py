from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel


class CallRequest(BaseModel):
    call_id: UUID
    to_e164: str
    language: str
    first_message: str
    voicemail_message: str
    key_points: str
    dynamic_variables: dict[str, str]


class ConversationRecord(BaseModel):
    conversation_id: str
    outcome: str | None = None
    status: str
    input_mode: str | None = None
    duration_s: int | None = None
    transcript: str | None = None


@dataclass(frozen=True)
class CallSimulation:
    outcome: str
    input_mode: str | None
    duration_s: int
    delay_s: float


class VoiceProvider(Protocol):
    async def start_call(self, call: CallRequest) -> str: ...

    async def get_conversation(self, conversation_id: str) -> ConversationRecord: ...

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> bool: ...

    async def simulate(self, attempt_no: int, seed: int) -> CallSimulation: ...

    async def close(self) -> None: ...
