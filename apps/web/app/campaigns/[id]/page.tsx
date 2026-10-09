"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, Campaign, CallRecord, languageNames, outcomeNames } from "../../lib/api";
import { Loading, Shell } from "../../components/Shell";

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [calls, setCalls] = useState<CallRecord[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const refresh = useCallback(async () => {
    try { const [item, rows] = await Promise.all([api<Campaign>(`/campaigns/${id}`), api<CallRecord[]>(`/campaigns/${id}/calls`)]); setCampaign(item); setCalls(rows); }
    catch (e) { setError((e as Error).message); }
  }, [id]);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 2500); return () => window.clearInterval(timer); }, [refresh]);
  async function action(path: string, label: string) {
    setBusy(true); setError(""); setMessage("");
    try { const result = await api<{ queued?: number }>(`/campaigns/${id}/${path}`, { method: "POST" }); setMessage(path === "retry" ? `${result.queued ?? 0} non-responders queued for retry.` : label); await refresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function saveScript(language: string, first_message: string, voicemail_message: string, key_points: string) {
    await api(`/campaigns/${id}/scripts/${language}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ first_message, voicemail_message, key_points }) });
    await refresh();
  }
  if (!campaign) return <Shell><div className="content">{error ? <div className="error-panel">{error}</div> : <Loading message="Loading campaign…"/>}</div></Shell>;
  const summary = campaign.summary;
  const eligible = calls.some(call => ["no_answer", "voicemail", "failed"].includes(call.outcome ?? "") && call.attempt < 3);
  return <Shell active="detail"><div className="content">
    <Link className="back-link" href="/campaigns">← All campaigns</Link>
    <div className="page-heading detail-heading"><div><div className="eyebrow">{campaign.template_id === "clinic_reminder" ? "CLINIC REMINDER" : "WORKSHOP INVITATION"} · {new Date(campaign.created_at).toLocaleDateString()}</div><h1>{campaign.name}</h1><p>{campaign.contact_count} contacts <span className="middot">·</span> {campaign.languages.map(l => languageNames[l] ?? l).join(", ")}</p></div><span className={`status status-${campaign.status}`}>{campaign.status}</span></div>
    {error && <div className="error-panel">{error}</div>}{message && <div className="success-panel">{message}</div>}
    <div className="stats-grid detail-stats">{[{ label: "Confirmed", value: summary.outcomes.confirmed ?? 0, note: "Will attend", icon: "✓" }, { label: "Declined", value: summary.outcomes.declined ?? 0, note: "Cannot attend", icon: "×" }, { label: "No answer", value: summary.outcomes.no_answer ?? 0, note: "Retryable", icon: "◷" }, { label: "Voicemail", value: summary.outcomes.voicemail ?? 0, note: "Retryable", icon: "▣" }].map(s => <article className="stat-card" key={s.label}><div className="stat-top"><span>{s.label}</span><i>{s.icon}</i></div><strong>{s.value}</strong><small>{s.note}</small></article>)}</div>
    <div className="detail-grid"><section className="panel"><div className="section-heading"><div><h2>Audience by language</h2><p>Latest outcome for each contact</p></div></div>{Object.entries(summary.by_language).length ? <div className="breakdown-list">{Object.entries(summary.by_language).map(([language, outcomes]) => { const amount = Object.values(outcomes).reduce((a, b) => a + b, 0); const yes = outcomes.confirmed ?? 0; return <div className="breakdown-row" key={language}><div className="breakdown-title"><b>{languageNames[language] ?? language}</b><span>{yes} of {amount} confirmed</span></div><div className="progress-track"><i style={{ width: `${amount ? yes / amount * 100 : 0}%` }}/></div><div className="outcome-breakdown">{Object.entries(outcomes).filter(([, count]) => count > 0).map(([outcome, count]) => <span key={outcome}>{outcomeNames[outcome] ?? outcome} <b>{count}</b></span>)}</div></div>; })}</div> : <div className="quiet-empty">Launch the campaign to see audience outcomes.</div>}</section>
      <section className="panel"><div className="section-heading"><div><h2>By segment</h2><p>Latest results by group</p></div></div>{Object.entries(summary.by_segment).length ? <div className="segment-list">{Object.entries(summary.by_segment).map(([segment, outcomes]) => <div className="segment-row" key={segment}><b>{segment}</b><span>{Object.values(outcomes).reduce((a, b) => a + b, 0)} people</span><div className="outcome-breakdown">{Object.entries(outcomes).filter(([, count]) => count > 0).map(([outcome, count]) => <span key={outcome}>{outcomeNames[outcome] ?? outcome} <b>{count}</b></span>)}</div></div>)}</div> : <div className="quiet-empty">Segments will appear here.</div>}</section></div>
    <section className="panel script-panel"><div className="section-heading"><div><h2>Campaign scripts</h2><p>Review the mock-generated message for each language before dialing.</p></div><span className="approval-pill">{campaign.approved ? "✓ Approved" : "Needs approval"}</span></div><div className="script-list">{campaign.scripts.map(script => <details className="script-card" key={script.language}><summary><span className="language-chip">{script.language.toUpperCase()}</span><b>{languageNames[script.language] ?? script.language}</b><span className="script-status">{script.approved ? "Approved" : "Draft"}</span></summary><ScriptEditor campaignStatus={campaign.status} script={script} onSave={saveScript}/></details>)}</div>{campaign.status === "draft" && <div className="script-actions"><button className="primary-button" onClick={() => void action("approve", "All language scripts approved.")} disabled={busy}>Approve scripts</button></div>}</section>
    <section className="panel"><div className="section-heading"><div><h2>Call activity</h2><p>{summary.completed_calls} of {campaign.contact_count} calls simulated · phone numbers are masked</p></div><div className="call-actions">{campaign.status === "ready" && <button className="primary-button" disabled={busy} onClick={() => void action("launch", "Mock campaign launched.")}>▶ Simulate campaign</button>}{campaign.status === "running" && <span className="running-label"><i/> Simulating calls…</span>}{campaign.status === "done" && eligible && <button className="secondary-button" disabled={busy} onClick={() => void action("retry", "Retries started.")}>↻ Retry non-responders</button>}</div></div>{calls.length ? <div className="table-wrap"><table><thead><tr><th>Contact</th><th>Language</th><th>Segment</th><th>Attempt</th><th>Outcome</th><th>Mode</th></tr></thead><tbody>{calls.map(call => <tr key={call.id}><td><b>{call.name}</b><small>{call.phone}</small></td><td>{languageNames[call.language] ?? call.language}</td><td>{call.segment}</td><td>{call.attempt}</td><td><span className={`outcome outcome-${call.outcome ?? call.state}`}>{outcomeNames[call.outcome ?? call.state] ?? call.state}</span></td><td>{call.input_mode ?? "—"}</td></tr>)}</tbody></table></div> : <div className="quiet-empty">Approve your scripts, then simulate this campaign. No real calls are placed in mock mode.</div>}</section>
    <footer><span>Mock mode · No calls placed to real numbers</span><span><i className="footer-dot"/> Contact details encrypted at rest</span></footer>
  </div></Shell>;
}

function ScriptEditor({ campaignStatus, script, onSave }: { campaignStatus: string; script: { language: string; first_message: string; voicemail_message: string; key_points: string }; onSave: (language: string, first_message: string, voicemail_message: string, key_points: string) => Promise<void> }) {
  const [message, setMessage] = useState(script.first_message);
  const [voicemail, setVoicemail] = useState(script.voicemail_message);
  const [saved, setSaved] = useState(false);
  return <div className="script-editor"><label>Opening message<textarea value={message} disabled={campaignStatus !== "draft"} onChange={e => setMessage(e.target.value)}/></label><label>Voicemail message<textarea value={voicemail} disabled={campaignStatus !== "draft"} onChange={e => setVoicemail(e.target.value)}/></label>{campaignStatus === "draft" && <button className="text-button" onClick={() => void onSave(script.language, message, voicemail, script.key_points).then(() => setSaved(true))}>{saved ? "✓ Saved" : "Save edits"}</button>}</div>;
}
