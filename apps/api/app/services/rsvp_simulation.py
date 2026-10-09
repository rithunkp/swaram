"""Run RSVP conversations against an ElevenLabs agent using its simulation test API."""

import asyncio
import copy
import json
from collections.abc import Mapping
from typing import Any

import httpx

SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "key": "yes",
        "name": "Hackathon RSVP · Yes",
        "persona": (
            "You are receiving a call from the hackathon organizer about the hackathon you registered "
            "for. You have decided to attend. When asked, say naturally in your own words that you "
            "will attend. Stay the recipient throughout; do not say you are calling, that you called "
            "the wrong number, or introduce another event. Do not repeat a supplied sentence verbatim."
        ),
        "expected": "confirmed",
    },
    {
        "key": "no",
        "name": "Hackathon RSVP · No",
        "persona": (
            "You are receiving a call from the hackathon organizer about the hackathon you registered "
            "for. You cannot attend. When asked, decline naturally in your own words. Stay the "
            "recipient throughout; do not say you are calling, that you called the wrong number, or "
            "introduce another event. Do not repeat a supplied sentence verbatim."
        ),
        "expected": "declined",
    },
    {
        "key": "ambiguous",
        "name": "Hackathon RSVP · Unsure",
        "persona": (
            "You are receiving a call from the hackathon organizer about the hackathon you registered "
            "for. You have not decided whether you can attend. Give a natural, uncertain answer in "
            "your own words and briefly explain a plausible reason. Stay the recipient throughout; do "
            "not say you are calling, that you called the wrong number, or introduce another event. "
            "Do not agree to attend or decline. Do not repeat a supplied sentence verbatim."
        ),
        "expected": "maybe",
    },
)

SUPPORTED_OUTCOMES = {
    "confirmed": "confirmed",
    "yes": "confirmed",
    "declined": "declined",
    "no": "declined",
    "maybe": "maybe",
    "ambiguous": "maybe",
    "uncertain": "maybe",
    "callback": "callback",
    "call back": "callback",
    "optout": "optout",
    "opt out": "optout",
    "other": "other",
}

RSVP_FIRST_MESSAGE = (
    "Hi, I'm calling from Swaram about the hackathon you registered for. "
    "Will you be attending?"
)
RSVP_ORGANIZER_PROMPT = """You are Swaram's friendly hackathon RSVP organizer calling a person who registered for the event.
Your only purpose is to learn whether they will attend.

Start with a brief greeting and ask if they will attend the hackathon. Listen to their own words. If the answer is unclear, ask one short, neutral follow-up. Do not ask about appointments, meetings, or unrelated events. Never say the participant called you or that they reached the wrong number; you initiated this conversation.

After the participant has answered, call record_outcome exactly once. Set outcome to confirmed only for a clear yes, declined only for a clear no, and maybe if they are uncertain, conditional, or still ambiguous. Set exact_response to the participant's relevant words verbatim. Do not rewrite, infer, or invent their reply. If they remain unsure after one clarification, use maybe. Then briefly acknowledge their answer and end politely."""

OUTCOME_TOOL_CONFIG = {
    "type": "client",
    "name": "record_outcome",
    "description": (
        "Record the registrant's event response after they answer. Call exactly once. "
        "Use confirmed, declined, maybe, callback, optout, or other based on their actual words. "
        "Copy the relevant participant words verbatim into exact_response."
    ),
    "expects_response": False,
    "parameters": {
        "type": "object",
        "required": ["outcome", "exact_response"],
        "properties": {
            "outcome": {
                "type": "string",
                "enum": ["confirmed", "declined", "maybe", "callback", "optout", "other"],
                "description": "Classify the participant's actual response. Use other when none fit.",
            },
            "exact_response": {
                "type": "string",
                "description": "The participant's relevant words, copied verbatim.",
            },
        },
    },
}


class ElevenLabsSimulationError(RuntimeError):
    pass


class ElevenLabsRsvpSimulation:
    def __init__(self, api_key: str, *, timeout_s: float = 90.0) -> None:
        self.client = httpx.AsyncClient(
            base_url="https://api.elevenlabs.io",
            headers={"xi-api-key": api_key},
            timeout=httpx.Timeout(timeout_s),
        )

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        response = await self.client.get(f"/v1/convai/agents/{agent_id}")
        self._raise_for_status(response, "read the configured ElevenLabs agent")
        result = response.json()
        if not isinstance(result, dict):
            raise ElevenLabsSimulationError("ElevenLabs returned an invalid agent configuration")
        return result

    @staticmethod
    def is_rsvp_agent(agent: dict[str, Any]) -> bool:
        conversation = agent.get("conversation_config")
        agent_config = conversation.get("agent") if isinstance(conversation, dict) else None
        prompt_config = agent_config.get("prompt") if isinstance(agent_config, dict) else None
        prompt_text = prompt_config.get("prompt", "") if isinstance(prompt_config, dict) else ""
        tools = prompt_config.get("tools", []) if isinstance(prompt_config, dict) else []
        tool_names = {
            str(tool.get("name", "")).casefold()
            for tool in tools
            if isinstance(tool, dict)
        } if isinstance(tools, list) else set()
        event_context = f"{prompt_text} {agent_config.get('first_message', '') if isinstance(agent_config, dict) else ''}".casefold()
        return (
            any(word in event_context for word in ("hackathon", "event registration", "rsvp"))
            and "record_outcome" in tool_names
        )

    async def create_outcome_tool(self) -> str:
        response = await self.client.post(
            "/v1/convai/tools",
            json={"tool_config": copy.deepcopy(OUTCOME_TOOL_CONFIG)},
        )
        self._raise_for_status(response, "create the mockable RSVP outcome tool")
        tool_id = response.json().get("id")
        if not isinstance(tool_id, str) or not tool_id:
            raise ElevenLabsSimulationError("ElevenLabs did not return the RSVP outcome tool ID")
        return tool_id

    async def create_rsvp_agent(
        self, source_agent: dict[str, Any], tool_id: str
    ) -> str:
        """Create a separate RSVP agent, preserving the source agent unchanged."""
        source_config = source_agent.get("conversation_config")
        if not isinstance(source_config, dict):
            raise ElevenLabsSimulationError("Could not read the source agent's conversation settings")
        conversation_config = copy.deepcopy(source_config)
        agent_config = conversation_config.setdefault("agent", {})
        if not isinstance(agent_config, dict):
            raise ElevenLabsSimulationError("The source agent has an unsupported conversation configuration")
        agent_config["first_message"] = RSVP_FIRST_MESSAGE
        source_prompt = source_config.get("agent", {}).get("prompt", {})
        agent_config["prompt"] = {
            "prompt": RSVP_ORGANIZER_PROMPT,
            "llm": source_prompt.get("llm") if isinstance(source_prompt, dict) else None,
            "temperature": 0.3,
            "tools": [],
            "tool_ids": [tool_id],
            "mcp_server_ids": [],
            "native_mcp_server_ids": [],
            "knowledge_base": [],
        }
        agent_config["prompt"]["llm"] = agent_config["prompt"]["llm"] or "gpt-4o-mini"
        agent_config.setdefault("language", "en")
        payload = {
            "name": "Swaram Hackathon RSVP Demo",
            "tags": ["swaram", "rsvp-demo"],
            "conversation_config": conversation_config,
        }
        response = await self.client.post("/v1/convai/agents/create", json=payload)
        self._raise_for_status(response, "create the dedicated RSVP organizer agent")
        agent_id = response.json().get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            raise ElevenLabsSimulationError("ElevenLabs did not return the RSVP organizer agent ID")
        return agent_id

    async def create_campaign_agent(self, source_agent: dict[str, Any], tool_id: str, language: str) -> str:
        """Create an isolated multilingual organizer agent for contact campaign simulations."""
        source_config = source_agent.get("conversation_config")
        if not isinstance(source_config, dict):
            raise ElevenLabsSimulationError("Could not read the source agent's conversation settings")
        conversation_config = copy.deepcopy(source_config)
        agent_config = conversation_config.setdefault("agent", {})
        if not isinstance(agent_config, dict):
            raise ElevenLabsSimulationError("The source agent has an unsupported conversation configuration")
        agent_config["language"] = language
        agent_config["first_message"] = "{{opening_message}}"
        source_prompt = source_config.get("agent", {}).get("prompt", {})
        agent_config["prompt"] = {
            "prompt": (
                "You are Swaram's friendly event RSVP organizer. Call the registrant by name when "
                "available. Speak in the requested contact language and use the approved opening "
                "message and event details. Ask whether they plan to attend; listen without steering "
                "them toward yes or no. If needed, ask one brief neutral follow-up. Their answer may "
                "be yes, no, uncertain, conditional, a callback request, an opt-out, or something "
                "else. Do not force a yes/no classification. After they answer, call record_outcome "
                "exactly once. Use confirmed for clear yes, declined for clear no, maybe for uncertain "
                "or conditional, callback for a callback request, optout for a clear request to stop "
                "future calls, and other for a response that does not fit. Copy the relevant participant "
                "words verbatim into exact_response. Then acknowledge briefly and end politely."
            ),
            "llm": source_prompt.get("llm") if isinstance(source_prompt, dict) else None,
            "temperature": 0.3,
            "tools": [],
            "tool_ids": [tool_id],
            "mcp_server_ids": [],
            "native_mcp_server_ids": [],
            "knowledge_base": [],
        }
        agent_config["prompt"]["llm"] = agent_config["prompt"]["llm"] or "gpt-4o-mini"
        payload = {
            "name": "Swaram Campaign RSVP Simulation",
            "tags": ["swaram", "campaign-simulation"],
            "conversation_config": conversation_config,
        }
        response = await self.client.post("/v1/convai/agents/create", json=payload)
        self._raise_for_status(response, "create the campaign simulation organizer agent")
        agent_id = response.json().get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            raise ElevenLabsSimulationError("ElevenLabs did not return the campaign simulation agent ID")
        return agent_id

    async def create_contact_test(
        self, *, user_id: str, name: str, language: str, language_name: str,
        event_context: str, opening_message: str, tool_id: str,
    ) -> str:
        """Create a natural participant persona; its answer is not preselected or outcome-scripted."""
        scenario = (
            f"You are {name}, a real person registered for the event. Your preferred language is "
            f"{language_name}. Have a brief, realistic conversation with the organizer about "
            f"attending. Decide your response yourself based on a plausible personal situation; "
            f"do not follow a preassigned yes/no/uncertain outcome. Respond naturally in {language_name}. "
            "You may say yes, no, that you are unsure or conditional, ask for a callback, ask not to "
            "be contacted again, or give another realistic response. Keep it conversational, do not "
            "announce that you are an AI or simulator, and do not repeat a supplied sample answer. "
            f"Simulation contact reference: {user_id}. Event context: {event_context}"
        )
        payload = {
            "type": "simulation",
            "name": f"Contact {user_id} · {language_name}",
            "simulation_scenario": scenario,
            "simulation_max_turns": 8,
            "success_conditions": [
                "The organizer asks about the registrant's plans for the event.",
                "The organizer records the answer once with record_outcome.",
                "The recorded classification and exact_response reflect what the participant actually said.",
            ],
            "tool_mock_config": {
                "mocking_strategy": "all", "fallback_strategy": "raise_error", "mocked_tool_ids": [tool_id],
            },
            "dynamic_variables": {
                "contact_name": name,
                "opening_message": opening_message,
                "language": language,
                "language_name": language_name,
            },
            "chat_history": [],
        }
        response = await self.client.post("/v1/convai/agent-testing/create", json=payload)
        self._raise_for_status(response, "create a contact simulation")
        test_id = response.json().get("id")
        if not isinstance(test_id, str) or not test_id:
            raise ElevenLabsSimulationError("ElevenLabs did not return a contact simulation test ID")
        return test_id

    async def run_test(self, agent_id: str, test_id: str, user_id: str) -> tuple[str, dict[str, Any]]:
        response = await self.client.post(
            f"/v1/convai/agents/{agent_id}/run-tests", json={"tests": [{"test_id": test_id}]}
        )
        self._raise_for_status(response, "start a contact simulation")
        invocation_id = response.json().get("id")
        if not isinstance(invocation_id, str) or not invocation_id:
            raise ElevenLabsSimulationError("ElevenLabs did not return a test invocation ID")
        for _ in range(90):
            await asyncio.sleep(2)
            response = await self.client.get(f"/v1/convai/test-invocations/{invocation_id}")
            self._raise_for_status(response, "read contact simulation results")
            runs = response.json().get("test_runs")
            if isinstance(runs, list):
                run = next((item for item in runs if isinstance(item, dict) and item.get("test_id") == test_id), None)
                if run is not None and self._terminal(run):
                    return invocation_id, self._result({"key": user_id}, run)
        raise ElevenLabsSimulationError("ElevenLabs contact simulation timed out after 180 seconds")

    async def ensure_tests(
        self, existing: Mapping[str, str], tool_id: str
    ) -> dict[str, str]:
        test_ids = dict(existing)
        for scenario in SCENARIOS:
            if scenario["key"] in test_ids:
                continue
            payload = {
                "type": "simulation",
                "name": scenario["name"],
                "simulation_scenario": scenario["persona"],
                "simulation_max_turns": 6,
                "success_conditions": [
                    "The organizer asks whether the registrant will attend the hackathon.",
                    "The organizer accurately captures the participant's RSVP using the "
                    "record_outcome tool with outcome " + scenario["expected"] + ".",
                    "The conversation preserves the participant's own words and does not "
                    "claim an answer they did not give.",
                ],
                "tool_mock_config": {
                    "mocking_strategy": "all",
                    "fallback_strategy": "raise_error",
                    "mocked_tool_ids": [tool_id],
                },
                "dynamic_variables": {},
                "chat_history": [],
            }
            response = await self.client.post("/v1/convai/agent-testing/create", json=payload)
            self._raise_for_status(response, "create an ElevenLabs simulation test")
            test_id = response.json().get("id")
            if not isinstance(test_id, str) or not test_id:
                raise ElevenLabsSimulationError("ElevenLabs did not return a simulation test ID")
            test_ids[scenario["key"]] = test_id
        return test_ids

    async def run_tests(
        self, agent_id: str, test_ids: Mapping[str, str]
    ) -> tuple[str, list[dict[str, Any]]]:
        response = await self.client.post(
            f"/v1/convai/agents/{agent_id}/run-tests",
            json={"tests": [{"test_id": test_id} for test_id in test_ids.values()]},
        )
        self._raise_for_status(response, "start the ElevenLabs RSVP simulations")
        invocation_id = response.json().get("id")
        if not isinstance(invocation_id, str) or not invocation_id:
            raise ElevenLabsSimulationError("ElevenLabs did not return a test invocation ID")

        for _ in range(60):
            await asyncio.sleep(2)
            response = await self.client.get(f"/v1/convai/test-invocations/{invocation_id}")
            self._raise_for_status(response, "read the ElevenLabs simulation results")
            invocation = response.json()
            runs = invocation.get("test_runs")
            if isinstance(runs, list) and len(runs) >= len(SCENARIOS):
                by_test_id = {
                    str(run.get("test_id")): run for run in runs if isinstance(run, dict)
                }
                matched = [by_test_id.get(test_ids[item["key"]]) for item in SCENARIOS]
                if all(run is not None and self._terminal(run) for run in matched):
                    return invocation_id, [
                        self._result(scenario, run)
                        for scenario, run in zip(SCENARIOS, matched, strict=True)
                        if run is not None
                    ]
        raise ElevenLabsSimulationError("ElevenLabs RSVP simulation timed out after 120 seconds")

    @staticmethod
    def _terminal(run: dict[str, Any]) -> bool:
        status = str(run.get("status", "")).casefold()
        return status not in {"", "pending", "queued", "running", "in_progress"}

    @staticmethod
    def _raise_for_status(response: httpx.Response, action: str) -> None:
        if response.is_error:
            if response.status_code in {401, 403}:
                detail = "Check the ElevenLabs API key, agent access, and Conversational AI permissions."
            elif response.status_code == 422:
                detail = "Check that the configured ElevenLabs agent supports Agent Testing simulations."
            else:
                detail = f"ElevenLabs returned HTTP {response.status_code}."
            raise ElevenLabsSimulationError(f"Could not {action}. {detail}")

    @staticmethod
    def _result(scenario: dict[str, str], run: dict[str, Any]) -> dict[str, Any]:
        messages = run.get("agent_responses")
        if not isinstance(messages, list):
            test_info = run.get("test_info")
            messages = test_info.get("chat_history", []) if isinstance(test_info, dict) else []

        transcript_lines: list[str] = []
        participant_lines: list[str] = []
        extracted: str | None = None
        extracted_response: str | None = None
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).casefold()
            message = item.get("message")
            if isinstance(message, str) and message.strip():
                speaker = "Participant simulator" if role == "user" else "Organizer agent"
                transcript_lines.append(f"{speaker}: {message.strip()}")
                if role == "user":
                    participant_lines.append(message.strip())
            tool_calls = item.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    if str(tool_call.get("tool_name", "")).casefold() != "record_outcome":
                        continue
                    params = tool_call.get("params_as_json")
                    if not isinstance(params, str):
                        continue
                    try:
                        arguments = json.loads(params)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(arguments, dict):
                        raw_outcome = str(arguments.get("outcome", "")).casefold()
                        extracted = SUPPORTED_OUTCOMES.get(raw_outcome, extracted)
                        raw_response = arguments.get("exact_response")
                        if isinstance(raw_response, str) and raw_response.strip():
                            extracted_response = raw_response.strip()

        return {
            "scenario": scenario["key"],
            "outcome": extracted or "maybe",
            "extraction_status": "captured" if extracted and extracted_response else "missing_tool_outcome",
            "exact_response": extracted_response or (participant_lines[-1] if participant_lines else ""),
            "transcript": "\n".join(transcript_lines),
            "test_id": run.get("test_id"),
            "status": run.get("status", "unknown"),
            "evaluation": (run.get("condition_result") or {}).get("result")
            if isinstance(run.get("condition_result"), dict)
            else None,
        }

    async def close(self) -> None:
        await self.client.aclose()
