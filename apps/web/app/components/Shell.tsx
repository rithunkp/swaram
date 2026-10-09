import Link from "next/link";

export function Shell({ children, active = "campaigns" }: { children: React.ReactNode; active?: string }) {
  return <main className="shell"><aside className="sidebar"><Link className="brand" href="/campaigns"><span className="brand-mark">s</span><span>Swaram<small>VOICE CAMPAIGNS</small></span></Link><div className="nav-label">WORKSPACE</div><Link className={`nav-item ${active === "campaigns" ? "active" : ""}`} href="/campaigns"><span>▦</span> Campaigns</Link><div className="nav-item muted"><span>◫</span> Templates</div><div className="sidebar-bottom"><div className="avatar">S</div><div><b>Sector 21</b><small>DEFINE 4.0 · PR 002</small></div><span className="dots">•••</span></div></aside><section className="main-panel"><header className="topbar"><div><span className="crumb">Workspace</span><span className="slash">/</span><b>{active === "detail" ? "Campaign details" : active === "new" ? "New campaign" : "Campaigns"}</b></div><div className="top-actions"><span className="mode"><i/> Mock mode</span><div className="user-avatar">R</div></div></header>{children}</section></main>;
}

export function Loading({ message = "Loading campaigns…" }: { message?: string }) { return <div className="notice-panel">{message}</div>; }
