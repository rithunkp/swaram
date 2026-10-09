"use client";

import { useCallback, useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
import { Shell } from "../components/Shell";

type TranscriptItem = { id: string; role: "user" | "agent"; text: string };

const agentId = process.env.NEXT_PUBLIC_ELEVENLABS_AGENT_ID ?? "";

export default function VoiceDemoPage() {
  return (
    <Shell active="voice-demo">
      <ConversationProvider>
        <VoiceDemo agentId={agentId} />
      </ConversationProvider>
    </Shell>
  );
}

function VoiceDemo({ agentId }: { agentId: string }) {
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const onMessage = useCallback((event: { event_id: number; source: "user" | "ai"; message: string }) => {
    const text = event.message?.trim();
    if (!text) return;
    setTranscript((items) => [...items, {
      id: `${event.event_id}-${items.length}`,
      role: event.source === "user" ? "user" : "agent",
      text,
    }]);
  }, []);
  const onError = useCallback((message: string) => setError(message), []);
  const conversation = useConversation({ onMessage, onError });
  const connected = conversation.status === "connected";
  const busy = starting;
  const phase = connected
    ? conversation.isSpeaking ? "Agent speaking" : conversation.isListening ? "Listening" : "Connected"
    : busy ? "Connecting" : "Ready for a browser conversation";

  async function start() {
    setError("");
    setTranscript([]);
    setStarting(true);
    try {
      await conversation.startSession({ agentId, connectionType: "webrtc" });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start the ElevenLabs conversation.");
    } finally {
      setStarting(false);
    }
  }

  async function end() {
    setError("");
    await conversation.endSession();
  }

  return (
    <div className="page voice-demo-page">
      <div className="page-heading voice-demo-heading">
        <div>
          <p className="eyebrow">ELEVENLABS · BROWSER VOICE SESSION</p>
          <h1>Talk to your agent</h1>
          <p>Speak through your laptop microphone and hear the agent respond here. This session does not dial a phone number or use Exotel.</p>
        </div>
        <span className="browser-only-pill"><i /> Browser only</span>
      </div>

      {!agentId && <div className="error-panel">Add your ElevenLabs Agent ID as <code>ELEVENLABS_AGENT_ID</code> in the project environment, then rebuild the web app.</div>}
      {error && <div className="error-panel" role="alert">{error}</div>}

      <div className="voice-demo-grid">
        <section className="panel voice-session-card">
          <div className={`voice-orb ${connected ? "voice-orb-active" : ""} ${conversation.isSpeaking ? "voice-orb-speaking" : ""}`}><span>✦</span></div>
          <span className={`voice-connection ${connected ? "connected" : ""}`}><i />{phase}</span>
          <p>Use a quiet room and allow microphone access when your browser asks. Start the session when you’re ready to speak.</p>
          <div className="voice-controls">
            {!connected ? (
              <button className="primary-button voice-start" disabled={!agentId || busy} onClick={() => void start()}>
                {busy ? "Connecting…" : "Start conversation"}
              </button>
            ) : (
              <>
                <button className="secondary-button" onClick={() => conversation.setMuted(!conversation.isMuted)}>
                  {conversation.isMuted ? "Unmute microphone" : "Mute microphone"}
                </button>
                <button className="primary-button voice-end" onClick={() => void end()}>End conversation</button>
              </>
            )}
          </div>
          <div className="voice-cost-note"><b>Provider:</b> ElevenLabs browser agent <span>·</span> <b>Phone carrier:</b> none <span>·</span> Conversation usage may count toward your ElevenLabs plan.</div>
        </section>

        <section className="panel voice-transcript-panel">
          <div className="section-heading"><div><h2>Conversation</h2><p>Live transcript from this browser session</p></div><span className="transcript-count">{transcript.length} messages</span></div>
          <div className="voice-transcript" aria-live="polite">
            {transcript.length ? transcript.map((item) => (
              <article className={`voice-message voice-message-${item.role}`} key={item.id}>
                <small>{item.role === "user" ? "You" : "ElevenLabs agent"}</small>
                <p>{item.text}</p>
              </article>
            )) : <div className="voice-transcript-empty"><span>◉</span><b>Your conversation will appear here</b><small>Start the session, then speak naturally.</small></div>}
          </div>
          <footer>This transcript stays in this page and is not saved to campaign contacts or call records.</footer>
        </section>
      </div>

      <div className="voice-demo-footnote">This is a live ElevenLabs voice conversation over the internet, not a simulated response. It tests browser audio and the agent; it does not test Exotel, a phone line, or campaign dialing.</div>
    </div>
  );
}
