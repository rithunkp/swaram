"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, Campaign } from "../lib/api";
import { Loading, Shell } from "../components/Shell";
import { useProviderMode } from "../lib/useProviderMode";

export default function CampaignList() {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [error, setError] = useState("");
  const refresh = useCallback(() => api<Campaign[]>("/campaigns").then(items => { setCampaigns(items); setError(""); }).catch((e: Error) => setError(e.message)), []);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 3000); return () => window.clearInterval(timer); }, [refresh]);
  const mode = useProviderMode();
  const total = campaigns?.reduce((sum, c) => sum + c.contact_count, 0) ?? 0;
  const confirmed = campaigns?.reduce((sum, c) => sum + (c.summary.outcomes.confirmed ?? 0), 0) ?? 0;
  const needs = campaigns?.reduce((sum, c) => sum + c.summary.retryable_contacts, 0) ?? 0;
  return <div className="content">
    <div className="page-heading"><div><div className="eyebrow">YOUR OUTREACH, AT A GLANCE</div><h1>Campaigns</h1><p>Bring every conversation together, in every language.</p></div><Link className="primary-button" href="/campaigns/new"><span>＋</span> New campaign</Link></div>
    <div className="stats-grid">{[{ label: "Active campaigns", value: campaigns?.filter(c => c.status === "running").length ?? 0, note: "Calls in progress", icon: "◷" }, { label: "People in campaigns", value: total, note: "Across all campaigns", icon: "◎" }, { label: "Confirmed", value: confirmed, note: "RSVPs received", icon: "✓" }, { label: "Needs follow-up", value: needs, note: "Eligible for another attempt", icon: "↗" }].map(item => <article className="stat-card" key={item.label}><div className="stat-top"><span>{item.label}</span><i>{item.icon}</i></div><strong>{item.value}</strong><small>{item.note}</small></article>)}</div>
    <section className="campaign-section"><div className="section-heading"><div><h2>Recent campaigns</h2><p>Your latest outreach activity</p></div><Link className="filter-button" href="/campaigns/new">Create a campaign <span>＋</span></Link></div>
      {error ? <div className="error-panel">Could not connect to Swaram API: {error}. Check that the API is running at {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}.</div> : campaigns === null ? <Loading /> : campaigns.length === 0 ? <div className="empty-state"><div className="empty-art"><div className="art-card card-back"/><div className="art-card card-front"><span className="art-wave">∿</span><i/><i/><i/></div><span className="art-spark spark-one">✳</span><span className="art-spark spark-two">✦</span></div><h3>Your first campaign starts here</h3><p>Invite a group, share a reminder, or check in. Swaram will help you reach everyone in the language they speak.</p><Link className="secondary-button" href="/campaigns/new">＋ Create your first campaign</Link></div> : <div className="campaign-list">{campaigns.map(campaign => <Link className="campaign-row" href={`/campaigns/${campaign.id}`} key={campaign.id}><div className="campaign-icon">{campaign.template_id === "clinic_reminder" ? "✚" : "◉"}</div><div className="campaign-name"><b>{campaign.name}</b><small>{campaign.contact_count} contacts · {campaign.languages.map(l => l.toUpperCase()).join(" · ")}</small></div><span className={`status status-${campaign.status}`}>{campaign.status}</span><div className="row-result"><b>{campaign.summary.outcomes.confirmed ?? 0}</b><small>confirmed</small></div><span className="row-arrow">→</span></Link>)}</div>}
    </section>
    <footer><span>Made for conversations that matter.</span><span><i className="footer-dot"/> {mode === "elevenlabs" ? "Live calling enabled" : mode === "mock" ? "Mock calls only" : "API status unavailable"} · v0.2.0</span></footer>
  </div>;
}
