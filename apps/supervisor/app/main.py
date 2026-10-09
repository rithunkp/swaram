from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.analysis import analyze_campaign, fingerprint
from app.store import Store


SWARAM_API_URL = os.getenv("SWARAM_API_URL", "http://localhost:8000").rstrip("/")
SUPERVISOR_READ_TOKEN = os.getenv("SUPERVISOR_READ_TOKEN", "")
SUPERVISOR_ACTION_TOKEN = os.getenv("SUPERVISOR_ACTION_TOKEN", "")
SUPERVISOR_AUTO_RETRY = os.getenv("SUPERVISOR_AUTO_RETRY", "false").lower() == "true"
SUPERVISOR_ANALYSIS_MODE = os.getenv("SUPERVISOR_ANALYSIS_MODE", "rules").lower()
HF_TOKEN = os.getenv("HF_TOKEN", "")
SUPERVISOR_MODEL = os.getenv("SUPERVISOR_MODEL") or os.getenv("HF_MODEL", "")
MAX_ATTEMPTS = max(1, int(os.getenv("MAX_ATTEMPTS", "3")))
POLL_INTERVAL_S = max(5, int(os.getenv("SUPERVISOR_POLL_INTERVAL_S", "15")))
if SUPERVISOR_ANALYSIS_MODE not in {"rules", "huggingface"}:
    raise RuntimeError("SUPERVISOR_ANALYSIS_MODE must be 'rules' or 'huggingface'")
if SUPERVISOR_AUTO_RETRY and not SUPERVISOR_ACTION_TOKEN:
    raise RuntimeError("SUPERVISOR_AUTO_RETRY=true requires SUPERVISOR_ACTION_TOKEN")
store = Store(os.getenv("SUPERVISOR_DATABASE_PATH", "./data/supervisor.db"))
sync_lock = asyncio.Lock()
sync_state: dict[str, Any] = {"connected": False, "last_error": None}


class ReviewUpdate(BaseModel):
    status: Literal["resolved", "dismissed"]


async def llm_insights(client: httpx.AsyncClient, analysis: dict[str, Any]) -> list[str]:
    if SUPERVISOR_ANALYSIS_MODE != "huggingface":
        return []
    if not HF_TOKEN or not SUPERVISOR_MODEL:
        raise RuntimeError("Hugging Face supervisor analysis needs HF_TOKEN and a model")
    segment_groups = [
        {"group": f"segment_{index + 1}", "outcomes": values}
        for index, values in enumerate(analysis["by_segment"].values())
    ]
    aggregate = {
        key: analysis[key]
        for key in (
            "status", "contact_count", "attempted_contacts", "completed_contacts",
            "retryable_contacts", "average_duration_s", "response_rate", "outcomes",
            "by_language",
        )
    }
    aggregate["by_segment"] = segment_groups
    response = await client.post(
        "https://router.huggingface.co/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {HF_TOKEN}",
            "content-type": "application/json",
        },
        json={
            "model": SUPERVISOR_MODEL,
            "max_tokens": 700,
            "temperature": 0.2,
            "reasoning_effort": "low",
            "messages": [{
                "role": "user",
                "content": (
                    "Act as a campaign data analyst. Analyze only these aggregate campaign metrics. "
                    "Do not infer causes unsupported by the data. Return JSON with an `insights` array "
                    "of at most 4 concise strings. "
                    "Never ask to retry an opted-out person or exceed the configured attempt limit. "
                    "You cannot change campaign state or contact anyone.\n\n"
                    + json.dumps(aggregate, ensure_ascii=False)
                ),
            }],
        },
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    choices = body.get("choices", []) if isinstance(body, dict) else []
    if not isinstance(choices, list) or not choices:
        raise ValueError("Unexpected Hugging Face response choices")
    message = choices[0].get("message", {})
    result_text = message.get("content", "") if isinstance(message, dict) else ""
    if not isinstance(result_text, str) or not result_text.strip():
        raise ValueError("Hugging Face returned empty supervisor insights")
    start = result_text.find("{")
    if start < 0:
        raise ValueError("Supervisor model response did not contain a JSON object")
    result, _ = json.JSONDecoder().raw_decode(result_text, start)
    if not isinstance(result, dict) or not isinstance(result.get("insights"), list):
        raise ValueError("Unexpected supervisor analysis output")
    return [str(value)[:500] for value in result["insights"][:4] if isinstance(value, str)]


async def run_sync(client: httpx.AsyncClient) -> None:
    if not SUPERVISOR_READ_TOKEN:
        sync_state.update(connected=False, last_error="Read token is not configured")
        return
    async with sync_lock:
        try:
            response = await client.get(
                f"{SWARAM_API_URL}/supervision/snapshot",
                headers={"Authorization": f"Bearer {SUPERVISOR_READ_TOKEN}"},
                timeout=20,
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Invalid campaign snapshot")
            campaigns = body.get("campaigns", [])
            if not isinstance(campaigns, list):
                raise ValueError("Invalid campaign snapshot")
            observed_ids: set[str] = set()
            for campaign in campaigns:
                if not isinstance(campaign, dict) or not isinstance(campaign.get("id"), str):
                    continue
                campaign_id = campaign["id"]
                observed_ids.add(campaign_id)
                current_fingerprint = fingerprint(campaign)
                analysis = analyze_campaign(campaign, MAX_ATTEMPTS)
                review_candidates = analysis.pop("review_candidates")
                previous = store.get_snapshot(campaign_id)
                snapshot_changed = previous is None or current_fingerprint != fingerprint(previous)
                if snapshot_changed:
                    try:
                        insights = await llm_insights(client, analysis)
                    except (httpx.HTTPError, ValueError, RuntimeError):
                        insights = []
                    analysis["llm_insights"] = insights
                elif previous is not None:
                    old_analysis = store.get_analysis(campaign_id)
                    analysis["llm_insights"] = old_analysis.get("llm_insights", []) if old_analysis else []
                store.save_campaign(
                    campaign_id,
                    campaign,
                    analysis,
                    current_fingerprint,
                    review_candidates,
                )
                if SUPERVISOR_AUTO_RETRY and analysis["status"] == "done" and analysis["retryable_contacts"]:
                    if not store.has_retry_run(current_fingerprint):
                        try:
                            retry_response = await client.post(
                                f"{SWARAM_API_URL}/supervision/campaigns/{campaign_id}/retry",
                                headers={"Authorization": f"Bearer {SUPERVISOR_ACTION_TOKEN}"},
                                timeout=20,
                            )
                            retry_response.raise_for_status()
                            retry_result = retry_response.json()
                            queued = int(retry_result.get("queued", 0)) if isinstance(retry_result, dict) else 0
                            store.record_retry_run(current_fingerprint, campaign_id, queued)
                        except httpx.HTTPStatusError as exc:
                            if exc.response.status_code < 500:
                                store.record_retry_run(current_fingerprint, campaign_id, 0)
                        except httpx.HTTPError:
                            pass
            store.remove_missing_campaigns(observed_ids)
            sync_state.update(connected=True, last_error=None, last_sync=body.get("generated_at"))
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            sync_state.update(connected=False, last_error="Could not read Swaram campaign snapshot")


async def worker(client: httpx.AsyncClient) -> None:
    while True:
        await run_sync(client)
        await asyncio.sleep(POLL_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient() as client:
        task = asyncio.create_task(worker(client))
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Swaram External Supervisor", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "connected": bool(sync_state.get("connected")),
        "analysis_mode": SUPERVISOR_ANALYSIS_MODE,
        "auto_retry": SUPERVISOR_AUTO_RETRY,
        "last_sync": sync_state.get("last_sync"),
        "last_error": sync_state.get("last_error"),
    }


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    return {
        **sync_state,
        "analysis_mode": SUPERVISOR_ANALYSIS_MODE,
        "auto_retry": SUPERVISOR_AUTO_RETRY,
        "max_attempts": MAX_ATTEMPTS,
        "campaigns": store.campaign_rows(),
        "open_review_count": len(store.review_rows("open")),
    }


@app.get("/api/reviews")
def reviews(status: Literal["open", "resolved", "dismissed", "all"] = "open") -> list[dict[str, Any]]:
    return store.review_rows(None if status == "all" else status)


@app.post("/api/sync")
async def sync_now() -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        await run_sync(client)
    return {"connected": bool(sync_state.get("connected")), "last_error": sync_state.get("last_error")}


@app.patch("/api/reviews/{review_id}")
def update_review(review_id: str, body: ReviewUpdate) -> dict[str, Any]:
    result = store.resolve_review(review_id, body.status)
    if result is None:
        raise HTTPException(404, "Review item not found")
    return result
