"use client";

import { useCallback, useEffect, useState } from "react";
import { Shell } from "../components/Shell";
import { API_URL, api } from "../lib/api";

type Scenario = "yes" | "no" | "ambiguous";
type RsvpCall = {
  id: string;
  batch_id: string;
  scenario: Scenario;
  outcome: "confirmed" | "declined" | "maybe";
  exact_response: string;
  transcript: string;
  provider: "elevenlabs_simulation";
  extraction_status: "captured" | "missing_tool_outcome";
  test_id: string | null;
  invocation_id: string | null;
  created_at: string;
};
type RunStatus = "queued" | "running" | "completed" | "failed";
type RsvpRun = { run_id: string; status: RunStatus; error?: string | null; calls: RsvpCall[] };

const scenarioNames: Record<Scenario, string> = { yes: "Yes", no: "No", ambiguous: "Ambiguous" };
const outcomeNames: Record<RsvpCall["outcome"], string> = {
  confirmed: "Confirmed",
  declined: "Declined",
  maybe: "Ambiguous",
};
const wait = (milliseconds: number) => new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));

export default function RsvpDemo() {
  const [history, setHistory] = useState<RsvpCall[]>([]);
  const [results, setResults] = useState<RsvpCall[]>([]);
  const [run, setRun] = useState<RsvpRun | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api<RsvpCall[]>("/demo/rsvp/calls"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load saved ElevenLabs simulations.");
    }
  }, []);

  useEffect(() => { void loadHistory(); }, [loadHistory]);

  async function startSimulation() {
    setRunning(true);
    setError("");
    setResults([]);
    setRun(null);
    try {
      const started = await api<{ run_id: string; status: RunStatus }>("/demo/rsvp/runs", { method: "POST" });
      setRun({ ...started, calls: [] });
      for (let attempt = 0; attempt < 65; attempt += 1) {
        await wait(2000);
        const current = await api<RsvpRun>(`/demo/rsvp/runs/${started.run_id}`);
        setRun(current);
        if (current.status === "completed") {
          setResults(current.calls);
          await loadHistory();
          return;
        }
        if (current.status === "failed") {
          if (current.calls.length) {
            setResults(current.calls);
            await loadHistory();
          }
          setError(current.error || "ElevenLabs could not complete the RSVP simulation.");
          return;
        }
      }
      setError("The ElevenLabs simulation is taking longer than expected. Refresh the page to check saved results.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the ElevenLabs simulation.");
    } finally {
      setRunning(false);
    }
  }

  const stateText = run?.status === "queued" ? "Sending scenarios to ElevenLabs…"
    : run?.status === "running" ? "ElevenLabs agents are talking…"
      : "Waiting for ElevenLabs…";

  return <Shell active="rsvp-demo"><div className="content rsvp-content">
    <div className="page-heading">
      <div><div className="eyebrow">ELEVENLABS AGENT SIMULATION</div><h1>Hackathon RSVP</h1><p>Your organizer agent talks with an AI participant simulator in three separate RSVP roles.</p></div>
      <div className="rsvp-actions"><a className="secondary-button rsvp-export" href={`${API_URL}/demo/rsvp/calls.csv`} download>↓ Export CSV</a><button className="primary-button rsvp-start" onClick={() => void startSimulation()} disabled={running}><span>{running ? "◌" : "▶"}</span>{running ? "Agents are talking…" : "Start 3-scenario simulation"}</button></div>
    </div>

    <div className="rsvp-notice"><span>ⓘ</span><div><b>ElevenLabs agent simulation · No phone call</b><p>Swaram keeps your configured agent unchanged. If it is not already an RSVP organizer, the first run creates a separate RSVP agent using its voice and language settings, with a mockable record_outcome tool. ElevenLabs Agent Testing then runs that organizer against its generated AI participant in Yes, No, and Ambiguous roles. These are text simulations; no Exotel, PSTN number, microphone, or real webhook is used. ElevenLabs plan usage may apply.</p></div></div>

    <div className="rsvp-flow" aria-label="ElevenLabs simulation roles">
      <RoleCard index="1" title="Organizer · ElevenLabs agent" detail="A dedicated RSVP agent uses your source agent’s voice and language settings"/>
      <RoleCard index="2" title="Participant · Yes persona" detail="ElevenLabs simulated user answers naturally that they will attend"/>
      <RoleCard index="3" title="Participant · No / unsure personas" detail="Two more runs: one declines; one stays uncertain in their own words"/>
    </div>

    {error && <div className="error-panel" role="alert">{error}</div>}

    {running && <section className="rsvp-live panel" aria-live="polite">
      <div className="section-heading"><div><h2>Virtual call simulation in progress</h2><p>{stateText} · no phone line is being dialed.</p></div><span className="rsvp-live-pill"><i/> ELEVENLABS TEST</span></div>
      <div className="rsvp-chat"><div className="rsvp-message organizer"><small>ORGANIZER AGENT</small><p>“You registered for our hackathon. Will you attend?” is the scenario being tested against the configured agent.</p></div><div className="rsvp-message participant"><small>ELEVENLABS SIMULATED PARTICIPANT</small><p>Its responses are generated for each role by ElevenLabs during the conversation, rather than supplied by Swaram.</p></div></div>
    </section>}

    {results.length > 0 && <section className="panel rsvp-results"><div className="section-heading"><div><h2>This ElevenLabs run</h2><p>Generated conversations and extracted outcomes saved in Swaram.</p></div><span className="rsvp-saved-count">{results.length} / 3 saved</span></div>
      <div className="rsvp-result-grid">{results.map((call) => <RsvpResult key={call.id} call={call}/>)}</div>
    </section>}

    <section className="panel rsvp-history"><div className="section-heading"><div><h2>Saved ElevenLabs RSVP calls</h2><p>Most recent simulation results · {history.length} records shown</p></div><button className="text-button" onClick={() => void loadHistory()}>Refresh</button></div>
      {history.length === 0 ? <div className="quiet-empty">No ElevenLabs simulation runs yet. Start one to create the first three records.</div> : <div className="table-wrap"><table><thead><tr><th>PARTICIPANT ROLE</th><th>AGENT RSVP</th><th>PARTICIPANT’S EXACT WORDS</th><th>EXTRACTION</th><th>CREATED</th></tr></thead><tbody>{history.map((call) => <tr key={call.id}><td><b>{scenarioNames[call.scenario]}</b><small>{call.id.slice(0, 8)}</small></td><td><span className={`outcome outcome-${call.outcome}`}>{outcomeNames[call.outcome]}</span></td><td className="rsvp-exact-cell">{call.exact_response || "No participant text returned"}</td><td>{call.extraction_status === "captured" ? "Tool captured" : "Extraction missing · review"}</td><td>{new Date(call.created_at).toLocaleString()}</td></tr>)}</tbody></table></div>}
    </section>
    <footer><span><i className="footer-dot"/> ElevenLabs Agent Testing</span><span>Hackathon RSVP · No phone call</span></footer>
  </div></Shell>;
}

function RoleCard({ index, title, detail }: { index: string; title: string; detail: string }) {
  return <div className="rsvp-flow-step"><span className={`rsvp-step-number step-${index}`}>{index}</span><div><b>{title}</b><small>{detail}</small></div></div>;
}

function RsvpResult({ call }: { call: RsvpCall }) {
  const lines = call.transcript.split("\n").filter(Boolean);
  return <article className={`rsvp-result-card result-${call.scenario}`}><div className="rsvp-result-top"><span>{scenarioNames[call.scenario]} persona</span><span className={`outcome outcome-${call.outcome}`}>{outcomeNames[call.outcome]}</span></div><p>{call.exact_response || "The simulator did not return a participant reply."}</p><div className="rsvp-transcript">{lines.map((line, index) => <div key={`${call.id}-${index}`}>{line}</div>)}</div><small>{call.extraction_status === "captured" ? "Outcome from ElevenLabs record_outcome tool" : "No supported outcome tool call was captured"}</small></article>;
}
