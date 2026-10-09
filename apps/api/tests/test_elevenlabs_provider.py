import asyncio
import hashlib
import hmac
import json
import time
from uuid import uuid4

import httpx

from app.providers import CallRequest, ElevenLabsProvider


def test_twilio_outbound_call_uses_dynamic_vars_and_first_message() -> None:
    async def run() -> None:
        request_seen: httpx.Request | None = None

        def respond(request: httpx.Request) -> httpx.Response:
            nonlocal request_seen
            request_seen = request
            return httpx.Response(200, json={"success": True, "conversation_id": "conv_123"})

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="https://api.elevenlabs.io"
        )
        provider = ElevenLabsProvider("api-key", "agent-1", "phone-1", "webhook-secret", client=client)
        call = CallRequest(
            call_id=uuid4(),
            to_e164="+919876543210",
            language="ml",
            first_message="നമസ്കാരം",
            voicemail_message="വീണ്ടും വിളിക്കുക",
            key_points="venue=Kochi",
            dynamic_variables={"contact_name": "Maya", "call_id": "call-1"},
        )

        assert await provider.start_call(call) == "conv_123"
        assert request_seen is not None
        assert request_seen.url.path == "/v1/convai/twilio/outbound-call"
        assert request_seen.headers["xi-api-key"] == "api-key"
        body = json.loads(request_seen.read())
        client_data = body["conversation_initiation_client_data"]
        assert body["to_number"] == "+919876543210"
        assert client_data["conversation_config_override"]["agent"]["first_message"] == "നമസ്കാരം"
        assert client_data["dynamic_variables"]["contact_name"] == "Maya"
        await provider.close()

    asyncio.run(run())


def test_webhook_signature_checks_digest_and_timestamp() -> None:
    secret = "whsec_test"
    body = b'{"type":"post_call_transcription"}'
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    provider = ElevenLabsProvider("key", "agent", "phone", secret)
    assert provider.verify_webhook({"ElevenLabs-Signature": f"t={timestamp},v0={signature}"}, body)
    assert not provider.verify_webhook({"ElevenLabs-Signature": f"t={timestamp},v0=bad"}, body)
    assert not provider.verify_webhook({"ElevenLabs-Signature": "t=1,v0=bad"}, body)
    asyncio.run(provider.close())
