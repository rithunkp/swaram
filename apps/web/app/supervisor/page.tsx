"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, languageNames, outcomeNames } from "../lib/api";
import { Loading, Shell } from "../components/Shell";
import { useProviderMode } from "../lib/useProviderMode";
import {
  ReviewItem,
  SupervisorCampaign,
  SupervisorOverview,
  supervisorApi,
} from "../lib/supervisorApi";

export default function SupervisorPage() {
  const [overview, setOverview] = useState<SupervisorOverview | null>(null);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const providerMode = useProviderMode();

  const refresh = useCallback(async () => {
    try {
      const [summary, items] = await Promise.all([
        supervisorApi<SupervisorOverview>("/api/overview"),
        supervisorApi<ReviewItem[]>("/api/reviews"),
      ]);
      setOverview(summary);
      setReviews(items);
      setError("");
    } catch (reason) {
      setError((reason as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function syncNow() {
    setBusy(true);
    try {
      const result = await supervisorApi<{ connected: boolean; last_error?: string | null }>("/api/sync", { method: "POST" });
      await refresh();
      if (result.connected) setNotice("Supervisor snapshot refreshed.");
      else setError(result.last_error ?? "Could not connect to Swaram.");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function review(item: ReviewItem, status: "resolved" | "dismissed") {
    setBusy(true);
    try {
      await supervisorApi(`/api/reviews/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      setNotice(status === "resolved" ? "Case marked reviewed." : "Case dismissed.");
      await refresh();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function retry(campaign: SupervisorCampaign) {
    if (providerMode === "unavailable") {
      setError("Provider status is unavailable. Refresh before starting calls.");
      return;
    }
    if (providerMode === "elevenlabs" && !window.confirm(`This will place real calls to eligible, consented contacts in “${campaign.campaign_name}”. Continue?`)) return;
    setBusy(true);
    try {
      const result = await api<{ queued?: number }>(`/campaigns/${campaign.campaign_id}/retry`, { method: "POST" });
      setNotice(`${result.queued ?? 0} eligible contacts queued. Swaram enforces the attempt limit and call window.`);
      await refresh();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!overview && !error) return <Shell active="supervisor"><div className="content"><Loading message="Connecting to supervisor…"/></div></Shell>;

  const campaigns = overview?.campaigns ?? [];
  const totalContacts = campaigns.reduce((total, item) => total + item.contact_count, 0);
  const totalRetryable = campaigns.reduce((total, item) => total + item.retryable_contacts, 0);
  const activeCampaigns = campaigns.filter((item) => item.status === "running").length;

  return <Shell active="supervisor"><div className="content supervisor-page">
    <div className="page-heading"><div><div className="eyebrow">EXTERNAL CAMPAIGN SUPERVISOR</div><h1>Campaign oversight</h1><p>Independent analysis and human review across Swaram campaigns.</p></div><button className="secondary-button" disabled={busy} onClick={() => void syncNow()}>{busy ? "Refreshing…" : "↻ Refresh analysis"}</button></div>
    {error && <div className="error-panel">{error}</div>}{notice && <div className="success-panel">{notice}</div>}
    {overview && !overview.connected && <div className="notice-panel">Supervisor is running but cannot read Swaram yet. Configure matching <code>SUPERVISOR_READ_TOKEN</code> values for the API and supervisor service.</div>}
    {overview && <>
      <div className="supervisor-status"><span className={overview.connected ? "connected" : "disconnected"}><i/> {overview.connected ? "Connected to Swaram" : "Waiting for Swaram"}</span><span>Analysis: {overview.analysis_mode}</span><span>Automatic retries: {overview.auto_retry ? "enabled" : "off"}</span><span>Retry limit: {overview.max_attempts}</span></div>
      <div className="stats-grid supervisor-stats">{[
        { label: "Campaigns observed", value: campaigns.length },
        { label: "Contacts monitored", value: totalContacts },
        { label: "Campaigns active", value: activeCampaigns },
        { label: "Human review", value: overview.open_review_count },
      ].map((stat) => <article className="stat-card" key={stat.label}><div className="stat-top"><span>{stat.label}</span></div><strong>{stat.value}</strong></article>)}</div>

      <section className="panel"><div className="section-heading"><div><h2>Campaign analysis</h2><p>Outcome patterns, retry eligibility, and operational recommendations.</p></div></div>
        {campaigns.length ? <div className="supervisor-campaigns">{campaigns.map((campaign) => <CampaignAnalysis key={campaign.campaign_id} campaign={campaign} busy={busy} onRetry={() => void retry(campaign)}/>)}</div> : <div className="quiet-empty">No campaign snapshots yet. Start or create a campaign in Swaram; the supervisor syncs automatically.</div>}
      </section>

      <section className="panel"><div className="section-heading"><div><h2>Human review queue</h2><p>Uncertain replies and contacts still unresolved after the retry limit.</p></div><span className="approval-pill">{reviews.length} open</span></div>
        {reviews.length ? <div className="review-list">{reviews.map((item) => <article className="review-card" key={item.id}>
          <div className="review-card-top"><div><span className="review-kind">{item.kind === "uncertain_response" ? "UNCERTAIN RESPONSE" : "ATTEMPTS EXHAUSTED"}</span><h3>{outcomeNames[item.outcome] ?? item.outcome} · {languageNames[item.language] ?? item.language}</h3></div><span className="review-attempt">Attempt {item.attempt}</span></div>
          <p>{item.reason}</p><div className="review-context"><Link href={`/campaigns/${item.campaign_id}?call_id=${encodeURIComponent(item.call_id)}`}>Open {item.campaign_name} call</Link><span>{item.segment}</span></div>
          <div className="review-actions"><button className="secondary-button" disabled={busy} onClick={() => void review(item, "dismissed")}>Dismiss</button><button className="primary-button" disabled={busy} onClick={() => void review(item, "resolved")}>Mark reviewed</button></div>
        </article>)}</div> : <div className="quiet-empty">No cases need human review right now.</div>}
      </section>
      <footer><span>Supervisor reads outcome metadata only; it does not receive names, phone numbers, or transcripts.</span><span>Last sync: {overview.last_sync ? new Date(overview.last_sync).toLocaleString() : "not yet"}</span></footer>
    </>}
  </div></Shell>;
}

function CampaignAnalysis({ campaign, busy, onRetry }: { campaign: SupervisorCampaign; busy: boolean; onRetry: () => void }) {
  return <article className="supervisor-campaign">
    <div className="supervisor-campaign-heading"><div><Link href={`/campaigns/${campaign.campaign_id}`}><h3>{campaign.campaign_name}</h3></Link><span className={`status status-${campaign.status}`}>{campaign.status}</span></div><span>{campaign.attempted_contacts} / {campaign.contact_count} attempted</span></div>
    <div className="supervisor-metrics"><span><b>{campaign.response_rate === null ? "—" : `${Math.round(campaign.response_rate * 100)}%`}</b> response rate</span><span><b>{campaign.retryable_contacts}</b> retry eligible</span><span><b>{campaign.open_review_candidates}</b> review candidates</span><span><b>{campaign.average_duration_s === null ? "—" : `${campaign.average_duration_s}s`}</b> avg. call</span></div>
    {Object.keys(campaign.by_language).length > 0 && <div className="supervisor-language">{Object.entries(campaign.by_language).map(([language, values]) => <span key={language}>{languageNames[language] ?? language}: {values.confirmed} confirmed / {values.contacts}</span>)}</div>}
    {(campaign.recommendations.length > 0 || campaign.llm_insights.length > 0) && <div className="supervisor-insights"><b>{campaign.llm_insights.length ? "Analyst insights" : "Supervisor notes"}</b><ul>{[...campaign.recommendations, ...campaign.llm_insights].map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></div>}
    {campaign.status === "done" && campaign.retryable_contacts > 0 && <div className="supervisor-retry"><span>Bounded retry is available. Opt-outs and contacts at the attempt limit are excluded.</span><button className="secondary-button" disabled={busy} onClick={onRetry}>Retry eligible contacts</button></div>}
  </article>;
}
