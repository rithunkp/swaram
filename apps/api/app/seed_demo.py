import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import Campaign, Call, Contact, Script, engine, initialize, phone_hash, seal
from app.services.scripts import script_copy


def main() -> None:
    asyncio.run(initialize())
    with Session(engine) as session:
        existing = session.scalar(select(Campaign).where(Campaign.id == "demo-workshop-2026"))
        if existing:
            print(existing.id)
            return
        now = datetime.now(UTC)
        campaign = Campaign(
            id="demo-workshop-2026",
            name="Community Design Workshop",
            template_id="workshop_invite",
            fields='{"topic":"Community Design Workshop","venue":"Kochi Innovation Centre","date":"18 October","time":"10:30 AM","organiser":"Sector 21"}',
            languages='["en","hi","ml"]',
            status="done",
            created_at=now,
        )
        session.add(campaign)
        fields = {
            "topic": "Community Design Workshop", "venue": "Kochi Innovation Centre",
            "date": "18 October", "time": "10:30 AM", "organiser": "Sector 21",
        }
        for language in ("en", "hi", "ml"):
            first, voicemail = script_copy(language, campaign.template_id, fields)
            session.add(Script(id=str(uuid.uuid4()), campaign_id=campaign.id, language=language, first_message=first, voicemail_message=voicemail, key_points="Kochi Innovation Centre · 18 October · 10:30 AM", approved=True))
        segments = ("Designers", "Organizers", "Students", "Community")
        outcomes = ("confirmed", "declined", "maybe", "callback", "no_answer", "voicemail", "confirmed", "no_answer")
        for index in range(200):
            language = ("en", "hi", "ml")[index % 3]
            phone = f"+91{index + 1:010d}"
            contact_id = str(uuid.uuid4())
            contact = Contact(
                id=contact_id,
                campaign_id=campaign.id,
                name_enc=seal(f"Demo Contact {index + 1:03d}"),
                phone_enc=seal(phone),
                phone_hash=phone_hash(phone),
                language=language,
                segment=segments[index % len(segments)],
                opted_out=index in {37, 114},
            )
            session.add(contact)
            if contact.opted_out:
                continue
            outcome = outcomes[index % len(outcomes)]
            call_time = now - timedelta(minutes=200 - index)
            duration = 24 + index % 41
            session.add(Call(
                id=str(uuid.uuid4()), campaign_id=campaign.id, contact_id=contact_id,
                attempt_no=1, state="done", outcome=outcome,
                input_mode=("keypad" if index % 2 else "speech") if outcome in {"confirmed", "declined", "maybe", "callback"} else None,
                duration_s=duration,
                transcript_redacted=f"Caller response recorded as {outcome}.",
                recording_expires_at=now + timedelta(days=30), started_at=call_time,
                ended_at=call_time + timedelta(seconds=duration),
            ))
        session.commit()
        print(campaign.id)


if __name__ == "__main__":
    main()
