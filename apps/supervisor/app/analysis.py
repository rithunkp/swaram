from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any


RETRYABLE_OUTCOMES = {"no_answer", "voicemail", "failed"}
HUMAN_REVIEW_OUTCOMES = {"maybe", "callback"}
TERMINAL_STATES = {"done", "failed"}


def fingerprint(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def analyze_campaign(snapshot: dict[str, Any], max_attempts: int) -> dict[str, Any]:
    contacts = {str(item["ref"]): item for item in snapshot.get("contacts", [])}
    latest: dict[str, dict[str, Any]] = {}
    calls = snapshot.get("calls", [])
    for call in sorted(calls, key=lambda item: int(item["attempt"])):
        latest[str(call["contact_ref"])] = call
    attempted_refs = {
        str(call["contact_ref"]) for call in calls if call.get("state") != "queued"
    }

    outcomes: Counter[str] = Counter()
    by_language: dict[str, Counter[str]] = {}
    by_segment: dict[str, Counter[str]] = {}
    review_items: list[dict[str, Any]] = []
    retryable = 0
    active = 0
    attempted = len(attempted_refs)
    completed = 0
    responded = 0
    completed_by_language: Counter[str] = Counter()
    responded_by_language: Counter[str] = Counter()
    durations: list[int] = []

    for contact_ref, contact in contacts.items():
        call = latest.get(contact_ref)
        if call is None:
            outcome = "queued"
        else:
            outcome = str(call.get("outcome") or call.get("state") or "unknown")
            if call.get("state") not in TERMINAL_STATES:
                active += 1
            else:
                completed += 1
                completed_by_language[str(contact.get("language", "unknown"))] += 1
                if outcome in {"confirmed", "declined", "maybe", "callback", "optout"}:
                    responded += 1
                    responded_by_language[str(contact.get("language", "unknown"))] += 1
            if call.get("state") in TERMINAL_STATES and isinstance(call.get("duration_s"), int) and call["duration_s"] > 0:
                durations.append(call["duration_s"])
        outcomes[outcome] += 1
        language = str(contact.get("language", "unknown"))
        segment = str(contact.get("segment", "General"))
        by_language.setdefault(language, Counter())[outcome] += 1
        by_segment.setdefault(segment, Counter())[outcome] += 1

        if call is None or call.get("state") not in TERMINAL_STATES or contact.get("opted_out"):
            continue
        attempt = int(call.get("attempt", 0))
        if outcome in HUMAN_REVIEW_OUTCOMES:
            reason = "The person gave an uncertain response or requested follow-up."
            kind = "uncertain_response"
        elif outcome in RETRYABLE_OUTCOMES and attempt >= max_attempts:
            reason = f"Still unresolved after {attempt} attempts; the retry limit is {max_attempts}."
            kind = "attempts_exhausted"
        else:
            reason = ""
            kind = ""
        if reason:
            review_items.append({
                "case_key": f"{snapshot['id']}:{contact_ref}:{call['id']}:{kind}",
                "campaign_id": str(snapshot["id"]),
                "campaign_name": str(snapshot.get("name", "Campaign")),
                "contact_ref": contact_ref,
                "call_id": str(call["id"]),
                "language": language,
                "segment": segment,
                "outcome": outcome,
                "attempt": attempt,
                "kind": kind,
                "reason": reason,
            })
        if (
            not contact.get("opted_out")
            and outcome in RETRYABLE_OUTCOMES
            and attempt < max_attempts
        ):
            retryable += 1

    response_rate = round(responded / completed, 3) if completed else None
    average_duration = round(sum(durations) / len(durations)) if durations else None
    language_summary = {
        language: {
            "contacts": sum(counts.values()),
            "completed": completed_by_language[language],
            "confirmed": counts["confirmed"],
            "no_answer": counts["no_answer"],
            "voicemail": counts["voicemail"],
            "failed": counts["failed"],
            "response_rate": round(responded_by_language[language] / completed_by_language[language], 3)
            if completed_by_language[language] else None,
        }
        for language, counts in sorted(by_language.items())
    }
    segment_summary = {
        segment: dict(sorted(counts.items()))
        for segment, counts in sorted(by_segment.items())
    }

    recommendations: list[str] = []
    scripts = snapshot.get("scripts", [])
    if snapshot.get("status") == "draft":
        missing = len(snapshot.get("languages", [])) - sum(bool(script.get("approved")) for script in scripts)
        recommendations.append(
            f"Human script review is required for {max(0, missing)} language script(s) before launch."
        )
    if snapshot.get("status") == "done" and retryable:
        recommendations.append(
            f"{retryable} contact(s) are eligible for a bounded retry; opt-outs are excluded."
        )
    if review_items:
        recommendations.append(f"{len(review_items)} case(s) need human review.")
    if active:
        recommendations.append(f"{active} contact(s) still have active or queued calls.")
    if completed and outcomes["failed"] / completed >= 0.2:
        recommendations.append("Call failures are at least 20% of completed outcomes; inspect provider health.")

    rates = [
        value["response_rate"]
        for value in language_summary.values()
        if value["response_rate"] is not None and value["completed"] >= 5
    ]
    if len(rates) >= 2 and max(rates) - min(rates) >= 0.25:
        recommendations.append("Response rates differ by at least 25 percentage points across languages; review the language breakdown.")

    return {
        "campaign_id": str(snapshot["id"]),
        "campaign_name": str(snapshot.get("name", "Campaign")),
        "status": str(snapshot.get("status", "unknown")),
        "created_at": snapshot.get("created_at"),
        "contact_count": len(contacts),
        "attempted_contacts": attempted,
        "active_contacts": active,
        "completed_contacts": completed,
        "retryable_contacts": retryable,
        "open_review_candidates": len(review_items),
        "average_duration_s": average_duration,
        "response_rate": response_rate,
        "outcomes": dict(sorted(outcomes.items())),
        "by_language": language_summary,
        "by_segment": segment_summary,
        "recommendations": recommendations,
        "review_candidates": review_items,
    }
