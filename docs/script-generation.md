# Campaign script generation

Swaram creates a draft script for each selected language when a campaign is created. The default provider is local mock generation, so no model API call is made.

To enable Hugging Face Inference Providers, create a Hugging Face fine-grained token with **Make calls to Inference Providers** permission. Set these values in the ignored local `.env` file:

```dotenv
SCRIPT_PROVIDER_MODE=huggingface
HF_TOKEN=<your-hugging-face-token>
HF_MODEL=Qwen/Qwen3.8-27B:fastest
```

Swaram calls the Hugging Face OpenAI-compatible chat-completion router. `Qwen/Qwen3.8-27B:fastest` selects the fastest currently available inference provider for that model. The campaign language picker includes the 31 languages listed by ElevenLabs' agent language guide plus Malayalam. The script service sends the template ID, requested language, approved question, and campaign field values. It never sends names, phone numbers, CSV rows, or contact outcomes. The returned copy is validated against the required JSON fields; the `key_points` field is replaced with the organiser's source campaign facts. If generation fails, Swaram does not create a partial campaign. The selected Hugging Face model and the selected ElevenLabs voice still determine which languages produce good output; the picker does not claim to certify translation quality.

Generated copy is always a draft. Review every language, edit as needed, and approve the campaign before launching it. Mock mode intentionally generates only English, Hindi, and Malayalam; it returns a clear error for other choices instead of silently substituting English. Verify translation and pronunciation with fluent speakers before using generated scripts for live calls.
