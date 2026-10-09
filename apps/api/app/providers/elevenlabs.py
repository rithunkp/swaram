"""ElevenLabs outbound calling adapter using its native telephony integrations."""

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
        telephony_kind: str = "twilio",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if telephony_kind not in {"twilio", "exotel"}:
            raise ValueError("telephony_kind must be 'twilio' or 'exotel'")
        self.api_key = api_key
        self.agent_id = agent_id
        self.phone_number_id = phone_number_id
        self.webhook_secret = webhook_secret
        self.telephony_kind = telephony_kind
        self.client = client or httpx.AsyncClient(
            base_url="https://api.elevenlabs.io", timeout=httpx.Timeout(30.0)
        )

    async def start_call(self, call: CallRequest) -> str:
        payload = {
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
                                "You are making an approved campaign call. Speak only in language code "
                                f"{call.language}. Follow the approved message and campaign facts below. "
                                "Say the approved first message once, then wait for the response; it "
                                "already includes the attendance question. Accept a spoken answer or, "
                                "when keypad input is available, map 1 to confirmed and 2 to declined. "
                                "Call the configured record_outcome tool once with the call_id and "
                                "recognized outcome, and include input_mode when known. Do not invent "
                                "details or pressure the person. If they ask not to be called, record "
                                "optout immediately and end the call. After recording any outcome, end "
                                "the call politely. "
                                f"Approved facts: {call.key_points}. If voicemail answers, say only: "
                                f"{call.voicemail_message}"
                            )
                        },
                    },
                },
            },
        }
        if self.telephony_kind == "twilio":
            payload["call_recording_enabled"] = False
        response = await self.client.post(
            f"/v1/convai/{self.telephony_kind}/outbound-call",
            headers={"xi-api-key": self.api_key},
            json=payload,
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
        metadata = data.get("metadata") or {}
        transcript = data.get("transcript")
        transcript_text = None
        if isinstance(transcript, list):
            transcript_text = " ".join(
                str(turn.get("message", "")) for turn in transcript if isinstance(turn, dict)
            )
        return ConversationRecord(
            conversation_id=conversation_id,
            status=str(data.get("status", "unknown")),
            duration_s=metadata.get("call_duration_secs", data.get("call_duration_secs")),
            transcript=transcript_text,
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
