# Browser voice demo

The **Voice demo** page connects a user’s browser microphone and speakers directly to the configured ElevenLabs conversational agent using the official React SDK. It does not use an Exotel/Twilio number, dial a PSTN destination, launch a campaign, or save the displayed transcript to campaign records.

## Configuration

- Set `ELEVENLABS_AGENT_ID` in the local `.env` file.
- The browser demo requires that agent to allow browser conversations. The current agent has authentication disabled, so the Agent ID is used client-side; never put the ElevenLabs API key in a `NEXT_PUBLIC_*` variable.
- `docker-compose.yml` passes the non-secret Agent ID to the web build as `NEXT_PUBLIC_ELEVENLABS_AGENT_ID`.
- Rebuild/restart the web app after changing the Agent ID.
- The browser will prompt the user for microphone access after they click **Start conversation**.

The user starts and ends each session. A session sends live audio to ElevenLabs and may use plan credits. It is independent of `PROVIDER_MODE`; the campaign API can remain in mock mode while this browser voice session is active.

## Boundaries

This tests browser audio, agent response quality, and the configured conversational agent. It does not validate phone carrier authorization, Exotel applets, phone call audio routing, campaign outcome tools that require a call ID, or outbound campaign launching. The visible transcript is held in page state only.
