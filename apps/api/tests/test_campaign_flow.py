import base64
import importlib
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path.as_posix()}/test.db")
    monkeypatch.setenv("FERNET_KEY", base64.urlsafe_b64encode(b"f" * 32).decode())
    monkeypatch.setenv("HMAC_PHONE_KEY", "test-only-phone-hmac-key")
    monkeypatch.chdir(tmp_path)
    import app.main as service

    service = importlib.reload(service)
    service.Base.metadata.drop_all(service.engine)
    service.Base.metadata.create_all(service.engine)
    with TestClient(service.app) as test_client:
        yield test_client


def create_campaign(client: TestClient, csv_text: str | None = None) -> dict[str, object]:
    rows = csv_text or "name,phone,language,segment,opted_out\nAda,+910000000001,en,Designers,false\nBala,+910000000002,ml,Students,false\n"
    response = client.post(
        "/campaigns",
        files={"csv": ("contacts.csv", rows.encode(), "text/csv")},
        data={
            "template_id": "workshop_invite",
            "fields": '{"topic":"Design day","venue":"Kochi","date":"18 October","time":"10 AM","organiser":"Sector 21"}',
            "languages": '["en","ml"]',
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_mock_campaign_journey_masks_contacts_and_retries(client: TestClient) -> None:
    campaign = create_campaign(client)
    campaign_id = campaign["id"]
    assert campaign["contact_count"] == 2
    assert {script["language"] for script in campaign["scripts"]} == {"en", "ml"}
    assert client.post(f"/campaigns/{campaign_id}/approve").status_code == 200
    assert client.post(f"/campaigns/{campaign_id}/launch").status_code == 200
    calls = client.get(f"/campaigns/{campaign_id}/calls").json()
    assert len(calls) == 2
    assert all("000000" not in call["phone"] for call in calls)
    assert all(re.fullmatch(r"\+91•••••\d{4}", call["phone"]) for call in calls)
    assert client.get(f"/campaigns/{campaign_id}/summary").json()["completed_calls"] == 2


def test_invalid_csv_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/campaigns",
        files={"csv": ("contacts.csv", b"name,phone,language\nAda,not-a-number,en\n", "text/csv")},
        data={
            "template_id": "workshop_invite",
            "fields": '{"topic":"A","venue":"B","date":"C","time":"D","organiser":"E"}',
            "languages": '["en"]',
        },
    )
    assert response.status_code == 422


def test_opted_out_rows_are_not_queued(client: TestClient) -> None:
    campaign = create_campaign(client, "name,phone,language,segment,opted_out\nAda,+910000000001,en,Designers,true\nBala,+910000000002,ml,Students,false\n")
    campaign_id = campaign["id"]
    client.post(f"/campaigns/{campaign_id}/approve")
    client.post(f"/campaigns/{campaign_id}/launch")
    calls = client.get(f"/campaigns/{campaign_id}/calls").json()
    assert len(calls) == 1


def test_retry_stops_at_attempt_limit(client: TestClient) -> None:
    import app.main as service
    from app.providers import CallSimulation

    class NoAnswerProvider:
        async def simulate(self, attempt_no: int, seed: int) -> CallSimulation:
            return CallSimulation("no_answer", None, 20, 0)

    service.PROVIDER = NoAnswerProvider()
    campaign = create_campaign(client, "name,phone,language,segment\nAda,+910000000001,en,Designers\n")
    campaign_id = campaign["id"]
    client.post(f"/campaigns/{campaign_id}/approve")
    client.post(f"/campaigns/{campaign_id}/launch")
    client.post(f"/campaigns/{campaign_id}/retry")
    client.post(f"/campaigns/{campaign_id}/retry")
    response = client.post(f"/campaigns/{campaign_id}/retry")
    assert response.json()["queued"] == 0
    calls = client.get(f"/campaigns/{campaign_id}/calls").json()
    assert [call["attempt"] for call in calls] == [3, 2, 1]


def test_contact_details_are_encrypted_and_transcripts_redacted(client: TestClient) -> None:
    import app.main as service
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    campaign = create_campaign(client)
    with Session(service.engine) as session:
        contact = session.scalar(select(service.Contact).where(service.Contact.campaign_id == campaign["id"]))
        assert contact is not None
        assert "+910000000001" not in contact.phone_enc
        assert "Ada" not in contact.name_enc
        assert service.reveal(contact.phone_enc) == "+910000000001"
    assert service.redact("Reach me at +919876543210 or demo@example.com") == "Reach me at [phone] or [email]"


def test_campaign_deletion_erases_calls_and_contacts(client: TestClient) -> None:
    campaign = create_campaign(client)
    campaign_id = campaign["id"]
    client.post(f"/campaigns/{campaign_id}/approve")
    client.post(f"/campaigns/{campaign_id}/launch")
    assert client.delete(f"/campaigns/{campaign_id}").status_code == 204
    assert client.get(f"/campaigns/{campaign_id}").status_code == 404


def test_record_outcome_authenticates_and_applies_opt_out(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as service
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    monkeypatch.setenv("TOOL_SECRET", "tool-secret-test")
    campaign = create_campaign(client, "name,phone,language,segment\nAda,+910000000001,en,Designers\n")
    with Session(service.engine) as session:
        contact = session.scalar(select(service.Contact).where(service.Contact.campaign_id == campaign["id"]))
        assert contact is not None
        call = service.Call(id="call-test", campaign_id=campaign["id"], contact_id=contact.id)
        session.add(call)
        session.commit()

    response = client.post(
        "/voice/tools/record_outcome",
        headers={"X-Tool-Secret": "tool-secret-test"},
        json={"call_id": "call-test", "outcome": "optout", "input_mode": "speech"},
    )
    assert response.status_code == 200
    assert client.post(
        "/voice/tools/record_outcome", json={"call_id": "call-test", "outcome": "confirmed"}
    ).status_code == 401
    with Session(service.engine) as session:
        saved_call = session.get(service.Call, "call-test")
        assert saved_call is not None and saved_call.outcome == "optout"
        assert saved_call.contact.opted_out is True
