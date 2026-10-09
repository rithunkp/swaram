import asyncio
import random
from collections.abc import Mapping

from app.providers.base import CallRequest, CallSimulation, ConversationRecord


class MockProvider:
    outcomes = ("confirmed", "declined", "maybe", "callback", "no_answer", "voicemail", "confirmed", "no_answer")

    async def simulate(self, attempt_no: int, seed: int) -> CallSimulation:
        rng = random.Random(seed + attempt_no)
        delay = rng.uniform(0.05, 0.25)
        await asyncio.sleep(delay)
        outcome = self.outcomes[(seed + attempt_no) % len(self.outcomes)]
        input_mode = rng.choice(("speech", "keypad")) if outcome in {"confirmed", "declined", "maybe", "callback"} else None
        return CallSimulation(outcome, input_mode, rng.randint(18, 76), delay)

    async def start_call(self, call: CallRequest) -> str:
        return f"mock-{call.call_id}"

    async def get_conversation(self, conversation_id: str) -> ConversationRecord:
        return ConversationRecord(conversation_id=conversation_id, outcome="confirmed", status="done")

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> bool:
        return False

    async def close(self) -> None:
        return None
