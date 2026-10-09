"""ElevenLabs outbound calling adapter using its native Twilio integration."""

import hashlib
import hmac
import time
from collections.abc import Mapping

import httpx

from app.providers.base import CallRequest, CallSimulation, ConversationRecord


class ElevenLabsProvider:
    def __init__(
        self,
        api_key: str,
        agent_id: str,
        phone_number_id: str,
        webhook_secret: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.agent_id = agent_id
        self.phone_number_id = phone_number_id
        self.webhook_secret = webhook_secret
        self.client = client or httpx.AsyncClient(
            base_url="https://api.elevenlabs.io", timeout=httpx.Timeout(30.0)
        )

    async def start_call(self, call: CallRequest) -> str:
        response = await self.client.post(
            "/v1/convai/twilio/outbound-call",
            headers={"xi-api-key": self.api_key},
            json={
                "agent_id": self.agent_id,
                "agent_phone_number_id": self.phone_number_id,
                "to_number": call.to_e164,
                "conversation_initiation_client_data": {
                    "dynamic_variables": call.dynamic_variables,
                    "conversation_config_override": {
                        "agent": {
                            "first_message": call.first_message,
                            "language": call.language,
                            "prompt": {
                                "prompt": (
                                    f"You are making an approved campaign call. Speak only in language code "
                                    f"{call.language}. Follow the approved message and campaign facts below. "
                                    "Do not invent details or pressure the person. Respect requests to stop "
                                    "and record them as optout. Ask for the attendance outcome clearly. "
                                    f"Approved facts: {call.key_points}. If voicemail answers, say only: "
                                    f"{call.voicemail_message}"
                                )
                            },
                        }
                    },
                },
                "call_recording_enabled": False,
            },
        )
        response.raise_for_status()
        conversation_id = response.json().get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise RuntimeError("ElevenLabs response did not include a conversation_id")
        return conversation_id

    async def get_conversation(self, conversation_id: str) -> ConversationRecord:
        response = await self.client.get(
            f"/v1/convai/conversations/{conversation_id}",
            headers={"xi-api-key": self.api_key},
        )
        response.raise_for_status()
        data = response.json()
        return ConversationRecord(
            conversation_id=conversation_id,
            status=str(data.get("status", "unknown")),
            duration_s=data.get("call_duration_secs"),
            transcript=None,
        )

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> bool:
        signature = next(
            (value for key, value in headers.items() if key.lower() == "elevenlabs-signature"),
            "",
        )
        parts = dict(part.split("=", 1) for part in signature.split(",") if "=" in part)
        timestamp = parts.get("t", "")
        digest = parts.get("v0", "")
        try:
            if abs(time.time() - int(timestamp)) > 30 * 60:
                return False
        except (TypeError, ValueError):
            return False
        expected = hmac.new(
            self.webhook_secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        return bool(digest) and hmac.compare_digest(expected, digest)

    async def simulate(self, attempt_no: int, seed: int) -> CallSimulation:
        raise RuntimeError("Simulation is available only in mock provider mode")

    async def close(self) -> None:
        await self.client.aclose()
