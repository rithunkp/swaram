const summary = [
  { label: "Active campaigns", value: "0", note: "Ready when you are", icon: "◷" },
  { label: "People reached", value: "0", note: "Across all campaigns", icon: "◎" },
  { label: "Confirmed", value: "0", note: "RSVPs received", icon: "✓" },
  { label: "Needs follow-up", value: "0", note: "No answer or voicemail", icon: "↗" },
];

export default function Home() {
  return (
    <main className="shell">
      <aside className="sidebar">
        <a className="brand" href="#"><span className="brand-mark">s</span><span>Swaram<small>VOICE CAMPAIGNS</small></span></a>
        <div className="nav-label">WORKSPACE</div>
        <a className="nav-item active" href="#"><span>▦</span> Campaigns <span className="nav-count">0</span></a>
        <a className="nav-item muted" href="#"><span>◫</span> Templates</a>
        <div className="sidebar-bottom"><div className="avatar">S</div><div><b>Sector 21</b><small>DEFINE 4.0 · PR 002</small></div><span className="dots">•••</span></div>
      </aside>

      <section className="main-panel">
        <header className="topbar"><div><span className="crumb">Workspace</span><span className="slash">/</span><b>Campaigns</b></div><div className="top-actions"><span className="mode"><i /> Mock mode</span><button className="icon-button" aria-label="Notifications">♧</button><div className="user-avatar">R</div></div></header>
        <div className="content">
          <div className="page-heading"><div><div className="eyebrow">YOUR OUTREACH, AT A GLANCE</div><h1>Campaigns</h1><p>Bring every conversation together, in every language.</p></div><button className="primary-button" disabled><span>＋</span> New campaign <small>Coming soon</small></button></div>

          <div className="stats-grid">{summary.map((item) => <article className="stat-card" key={item.label}><div className="stat-top"><span>{item.label}</span><i>{item.icon}</i></div><strong>{item.value}</strong><small>{item.note}</small></article>)}</div>

          <section className="campaign-section"><div className="section-heading"><div><h2>Recent campaigns</h2><p>Your latest outreach activity</p></div><button className="filter-button" disabled>All campaigns <span>⌄</span></button></div>
            <div className="empty-state"><div className="empty-art"><div className="art-card card-back"/><div className="art-card card-front"><span className="art-wave">∿</span><i/><i/><i/></div><span className="art-spark spark-one">✳</span><span className="art-spark spark-two">✦</span></div><h3>Your first campaign starts here</h3><p>Invite a group, share a reminder, or check in. Swaram will help you reach everyone in the language they speak.</p><button className="secondary-button" disabled>＋ Create your first campaign</button><span className="soon-note">Campaign setup is coming soon</span></div>
          </section>
          <footer><span>Made for conversations that matter.</span><span><i className="footer-dot"/> All systems operational <b>·</b> v0.1.0</span></footer>
        </div>
      </section>
    </main>
  );
}
