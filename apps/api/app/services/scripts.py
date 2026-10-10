import json
from collections.abc import Mapping
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError


LANGUAGE_NAMES = {
    "ar": "Arabic", "bg": "Bulgarian", "zh": "Chinese", "hr": "Croatian",
    "cs": "Czech", "da": "Danish", "nl": "Dutch", "en": "English",
    "fil": "Filipino", "fi": "Finnish", "fr": "French", "de": "German",
    "el": "Greek", "hi": "Hindi", "hu": "Hungarian", "id": "Indonesian",
    "it": "Italian", "ja": "Japanese", "ko": "Korean", "ms": "Malay",
    "no": "Norwegian", "pl": "Polish", "pt": "Portuguese", "ro": "Romanian",
    "ru": "Russian", "sk": "Slovak", "es": "Spanish", "sv": "Swedish",
    "ta": "Tamil", "tr": "Turkish", "uk": "Ukrainian", "ml": "Malayalam",
}
MOCK_LANGUAGES = {"en", "hi", "ml"}


class GeneratedScript(BaseModel):
    first_message: str = Field(min_length=1, max_length=3000)
    voicemail_message: str = Field(min_length=1, max_length=1000)
    key_points: str = Field(default="", max_length=3000)


SCRIPT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "campaign_call_script",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "first_message": {"type": "string"},
                "voicemail_message": {"type": "string"},
                "key_points": {"type": "string"},
            },
            "required": ["first_message", "voicemail_message", "key_points"],
            "additionalProperties": False,
        },
    },
}


class ScriptGenerationError(RuntimeError):
    pass


class ScriptGenerator(Protocol):
    async def generate(
        self, language: str, template_id: str, fields: Mapping[str, str]
    ) -> GeneratedScript: ...

    async def close(self) -> None: ...


def parse_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise ValueError("Model response did not contain a JSON object")
    value, _ = json.JSONDecoder().raw_decode(text, start)
    if not isinstance(value, dict):
        raise ValueError("Model response JSON must be an object")
    return value


def script_copy(language: str, template_id: str, fields: Mapping[str, str]) -> tuple[str, str]:
    if template_id == "custom_message":
        message = fields["message"].strip()
        question = fields["question"].strip()
        voicemail = {
            "hi": "जानकारी साझा करने के लिए धन्यवाद।",
            "ml": "വിവരങ്ങൾ പങ്കുവെച്ചതിന് നന്ദി.",
        }.get(language, "Thank you for your response.")
        return f"{message} {question}", voicemail
    if template_id == "clinic_reminder":
        if language == "hi":
            return (
                f"नमस्ते, {fields['organiser']} की ओर से {fields['clinic']} का {fields['date']} को "
                f"{fields['time']} बजे अपॉइंटमेंट याद दिला रहे हैं। क्या आप आ पाएँगे?",
                "आपके अपॉइंटमेंट की याद दिलाने के लिए कॉल किया था।",
            )
        if language == "ml":
            return (
                f"നമസ്കാരം, {fields['organiser']} അറിയിക്കുന്നു: {fields['clinic']} സന്ദർശനം "
                f"{fields['date']} {fields['time']} മണിക്ക് ആണ്. നിങ്ങൾക്ക് വരാനാകുമോ?",
                "നിങ്ങളുടെ അപ്പോയിന്റ്മെന്റ് ഓർമ്മിപ്പിക്കാൻ വിളിച്ചതാണ്.",
            )
        return (
            f"Hello, {fields['organiser']} is reminding you about your appointment at "
            f"{fields['clinic']} on {fields['date']} at {fields['time']}. Can you attend?",
            "We called with a reminder about your appointment.",
        )
    if language == "hi":
        return (
            f"नमस्ते, {fields['organiser']} की ओर से {fields['topic']} के बारे में कॉल है। यह "
            f"{fields['date']} को {fields['time']} बजे {fields['venue']} में होगा। क्या आप आएँगे?",
            "कार्यशाला के निमंत्रण के लिए कॉल किया था। अधिक जानकारी के लिए आयोजक से संपर्क करें।",
        )
    if language == "ml":
        return (
            f"നമസ്കാരം, {fields['organiser']} അറിയിക്കുന്നു: {fields['topic']} {fields['date']} "
            f"{fields['time']} മണിക്ക് {fields['venue']} ൽ നടക്കും. നിങ്ങൾ പങ്കെടുക്കുമോ?",
            "ശില്പശാലയിലേക്ക് ക്ഷണിക്കാൻ വിളിച്ചതാണ്. കൂടുതൽ വിവരങ്ങൾക്ക് സംഘാടകരെ ബന്ധപ്പെടുക.",
        )
    return (
        f"Hello, this is a message from {fields['organiser']}. Join us for {fields['topic']} at "
        f"{fields['venue']} on {fields['date']} at {fields['time']}. Will you attend?",
        "We called to invite you to our workshop. Please contact the organizer for details.",
    )


class MockScriptGenerator:
    async def generate(
        self, language: str, template_id: str, fields: Mapping[str, str]
    ) -> GeneratedScript:
        if language not in MOCK_LANGUAGES:
            language_name = LANGUAGE_NAMES.get(language, language)
            raise ScriptGenerationError(
                f"Mock script generation cannot translate into {language_name}. "
                "Set SCRIPT_PROVIDER_MODE=huggingface to generate this language."
            )
        first_message, voicemail_message = script_copy(language, template_id, fields)
        return GeneratedScript(
            first_message=first_message,
            voicemail_message=voicemail_message,
            key_points=json.dumps(fields, ensure_ascii=False),
        )

    async def close(self) -> None:
        return None


class HuggingFaceScriptGenerator:
    def __init__(self, token: str, model: str, *, client: httpx.AsyncClient | None = None) -> None:
        self.model = model
        self.client = client or httpx.AsyncClient(
            base_url="https://router.huggingface.co/v1", timeout=httpx.Timeout(60.0)
        )
        self.headers = {
            "Authorization": f"Bearer {token}",
            "content-type": "application/json",
        }

    async def generate(
        self, language: str, template_id: str, fields: Mapping[str, str]
    ) -> GeneratedScript:
        language_name = LANGUAGE_NAMES.get(language)
        if language_name is None:
            raise ScriptGenerationError("Unsupported language code. Choose a listed language.")
        question = fields.get("question") if template_id == "custom_message" else (
            "Will you attend?" if template_id == "workshop_invite" else "Can you attend?"
        )
        prompt_data = json.dumps(
            {
                "template_id": template_id,
                "language": language_name,
                "approved_question": question,
                "campaign_facts": dict(fields),
            },
            ensure_ascii=False,
        )
        user_message = (
            "Write an outbound phone script for this campaign. Use the requested language. "
            "Keep the opening concise and polite. Preserve the event facts accurately, do not "
            "invent details, and ask the approved question. For a custom_message campaign, "
            "preserve the organizer's intended message and translate it faithfully. The voicemail must be brief and "
            "must not disclose personal contact details. Return the required JSON object with string "
            "fields first_message, voicemail_message, and key_points, without markdown or commentary. "
            "key_points must contain only "
            "facts supplied in campaign_facts.\n\n"
            f"Campaign input:\n{prompt_data}"
        )
        for attempt in range(2):
            try:
                request_body = {
                    "model": self.model,
                    "max_tokens": 1600,
                    "temperature": 0.2,
                    "reasoning_effort": "low",
                    "response_format": SCRIPT_RESPONSE_FORMAT,
                    "messages": [{"role": "user", "content": user_message}],
                }
                response = await self.client.post(
                    "/chat/completions",
                    headers=self.headers,
                    json=request_body,
                )
                # Some provider/model combinations do not accept constrained output or
                # reasoning controls. Retry without those optional parameters, then validate.
                if response.status_code == 400:
                    request_body.pop("response_format")
                    request_body.pop("reasoning_effort")
                    response = await self.client.post(
                        "/chat/completions",
                        headers=self.headers,
                        json=request_body,
                    )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("Unexpected script provider response")
                choices = body.get("choices", [])
                if not isinstance(choices, list) or not choices:
                    raise ValueError("Unexpected Hugging Face response choices")
                choice = choices[0]
                message = choice.get("message", {}) if isinstance(choice, dict) else {}
                text = message.get("content", "") if isinstance(message, dict) else ""
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("Hugging Face returned an empty script")
                output = parse_json_object(text)
                # The organizer's campaign facts are authoritative; discard any model rewrite.
                output["key_points"] = json.dumps(fields, ensure_ascii=False)
                return GeneratedScript.model_validate(output)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in {401, 403}:
                    raise ScriptGenerationError(
                        "Hugging Face authentication failed. Use a fresh token with Inference Providers permission."
                    ) from exc
                if status == 402:
                    raise ScriptGenerationError(
                        "Hugging Face rejected the request because inference billing or credits are unavailable."
                    ) from exc
                if status == 404:
                    raise ScriptGenerationError(
                        "Hugging Face could not route this model. Check its Inference Providers availability."
                    ) from exc
                if status == 429:
                    if attempt == 1:
                        raise ScriptGenerationError(
                            "Hugging Face rate limit reached. Wait briefly and retry."
                        ) from exc
                    continue
                if status < 500:
                    raise ScriptGenerationError(
                        f"Hugging Face rejected the script request (HTTP {status}). Check model/provider compatibility."
                    ) from exc
                if attempt == 1:
                    raise ScriptGenerationError(
                        f"Hugging Face inference is temporarily unavailable (HTTP {status}). Retry shortly."
                    ) from exc
            except httpx.HTTPError as exc:
                if attempt == 1:
                    raise ScriptGenerationError("Could not generate a valid script") from exc
            except (ValueError, ValidationError) as exc:
                if attempt == 0:
                    user_message += (
                        "\nThe prior response did not match the required fields. Return one valid "
                        "JSON object with non-empty string first_message and voicemail_message, "
                        "and a string key_points. Do not include markdown or commentary."
                    )
                    continue
                raise ScriptGenerationError("Hugging Face returned an invalid script") from exc
        raise ScriptGenerationError("Could not generate a valid script")

    async def close(self) -> None:
        await self.client.aclose()
