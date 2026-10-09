"use client";

import Link from "next/link";
import { useProviderMode } from "../lib/useProviderMode";

export function Shell({ children, active = "campaigns" }: { children: React.ReactNode; active?: string }) {
  const mode = useProviderMode();
  const modeLabel = mode === "elevenlabs" ? "Live calling enabled" : mode === "mock" ? "Mock mode · no real calls" : "API unavailable";
  return <main className="shell"><aside className="sidebar"><Link className="brand" href="/campaigns"><span className="brand-mark">s</span><span>Swaram<small>VOICE CAMPAIGNS</small></span></Link><div className="nav-label">WORKSPACE</div><Link className={`nav-item ${active === "campaigns" || active === "detail" || active === "new" ? "active" : ""}`} href="/campaigns"><span>▦</span> Campaigns</Link><Link className={`nav-item ${active === "rsvp-demo" ? "active" : ""}`} href="/rsvp-demo"><span>◉</span> RSVP simulation</Link><Link className={`nav-item ${active === "voice-demo" ? "active" : ""}`} href="/voice-demo"><span>◉</span> Voice demo</Link><Link className={`nav-item ${active === "supervisor" ? "active" : ""}`} href="/supervisor"><span>◉</span> Supervisor</Link><div className="nav-item muted"><span>◫</span> Templates</div><div className="sidebar-bottom"><div className="avatar">S</div><div><b>Sector 21</b><small>DEFINE 4.0 · PR 002</small></div><span className="dots">•••</span></div></aside><section className="main-panel"><header className="topbar"><div><span className="crumb">Workspace</span><span className="slash">/</span><b>{active === "detail" ? "Campaign details" : active === "new" ? "New campaign" : active === "supervisor" ? "Supervisor" : active === "voice-demo" ? "Voice demo" : active === "rsvp-demo" ? "RSVP simulation" : "Campaigns"}</b></div><div className="top-actions"><span className={`mode ${mode === "elevenlabs" ? "mode-live" : ""}`} title={mode === "elevenlabs" ? "Launching a campaign will place real phone calls" : undefined}><i/>{modeLabel}</span><div className="user-avatar">R</div></div></header>{children}</section></main>;
}

export function Loading({ message = "Loading campaigns…" }: { message?: string }) { return <div className="notice-panel">{message}</div>; }
