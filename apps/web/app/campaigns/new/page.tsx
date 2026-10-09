"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, languageNames } from "../../lib/api";
import { Shell } from "../../components/Shell";

type Template = { id: string; name: string; fields: string[] };
const labels: Record<string, string> = { topic: "Workshop topic", venue: "Venue", date: "Date", time: "Time", organiser: "Organizer", clinic: "Clinic" };

export default function NewCampaign() {
  const router = useRouter();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateId, setTemplateId] = useState("workshop_invite");
  const [values, setValues] = useState<Record<string, string>>({ topic: "Community Design Workshop", venue: "Kochi Innovation Centre", date: "18 October", time: "10:30 AM", organiser: "Sector 21" });
  const [file, setFile] = useState<File | null>(null);
  const [languages, setLanguages] = useState(["en", "hi", "ml"]);
  const [languageToAdd, setLanguageToAdd] = useState("ar");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { void api<Template[]>("/templates").then(setTemplates).catch((e: Error) => setError(e.message)); }, []);
  const selected = templates.find(t => t.id === templateId);
  function chooseTemplate(id: string) {
    setTemplateId(id);
    const template = templates.find(t => t.id === id);
    if (!template) return;
    const defaults: Record<string, string> = id === "clinic_reminder" ? { clinic: "City Care Clinic", date: "20 October", time: "2:00 PM", organiser: "Sector 21" } : { topic: "Community Design Workshop", venue: "Kochi Innovation Centre", date: "18 October", time: "10:30 AM", organiser: "Sector 21" };
    setValues(Object.fromEntries(template.fields.map(field => [field, defaults[field] ?? ""])));
  }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) { setError("Choose a CSV contact list to continue."); return; }
    setBusy(true); setError("");
    const body = new FormData();
    body.append("csv", file); body.append("template_id", templateId); body.append("fields", JSON.stringify(values)); body.append("languages", JSON.stringify(languages));
    try { const campaign = await api<{ id: string }>("/campaigns", { method: "POST", body }); router.push(`/campaigns/${campaign.id}`); }
    catch (e) { setError((e as Error).message); setBusy(false); }
  }
  return <Shell active="new"><div className="content narrow-content">
    <Link className="back-link" href="/campaigns">← Back to campaigns</Link><div className="page-heading compact-heading"><div><div className="eyebrow">START A CONVERSATION</div><h1>New campaign</h1><p>Choose a template, add the details, and pick your audience’s languages.</p></div></div>
    <form onSubmit={submit} className="form-stack">
      <section className="form-card"><div className="form-step"><span>1</span><div><h2>Choose a template</h2><p>Start from a message tailored to your campaign.</p></div></div><div className="template-options">{templates.map(t => <button type="button" key={t.id} onClick={() => chooseTemplate(t.id)} className={`template-option ${templateId === t.id ? "selected" : ""}`}><span className="template-symbol">{t.id === "clinic_reminder" ? "✚" : "◉"}</span><span><b>{t.name}</b><small>{t.fields.length} details to fill in</small></span><i>{templateId === t.id ? "●" : "○"}</i></button>)}</div></section>
      <section className="form-card"><div className="form-step"><span>2</span><div><h2>Campaign details</h2><p>These facts will be included in each language script.</p></div></div><div className="field-grid">{(selected?.fields ?? []).map(field => <label className="field" key={field}><span>{labels[field] ?? field}</span><input required value={values[field] ?? ""} onChange={e => setValues({ ...values, [field]: e.target.value })} placeholder={labels[field] ?? field}/></label>)}</div><div className="language-picker"><span className="field-label">Script languages</span><div className="language-add"><select value={languageToAdd} onChange={e => setLanguageToAdd(e.target.value)} aria-label="Choose a script language">{Object.entries(languageNames).filter(([code]) => !languages.includes(code)).map(([code, name]) => <option key={code} value={code}>{name}</option>)}</select><button type="button" className="secondary-button" onClick={() => setLanguages([...languages, languageToAdd])} disabled={languages.includes(languageToAdd)}>Add language</button></div><div className="language-selected">{languages.map(code => <span className="language-pill" key={code}>{languageNames[code] ?? code}<button type="button" aria-label={`Remove ${languageNames[code] ?? code}`} onClick={() => setLanguages(languages.filter(item => item !== code))}>×</button></span>)}</div><small className="language-hint">Additional language scripts use the configured Hugging Face model. Mock script mode only provides English, Hindi, and Malayalam.</small></div></section>
      <section className="form-card"><div className="form-step"><span>3</span><div><h2>Add contacts</h2><p>Upload user_id, name, phone, and language. Segment is optional.</p></div></div><label className="upload-box"><input type="file" accept=".csv,text/csv" onChange={e => setFile(e.target.files?.[0] ?? null)} required/><span className="upload-icon">↑</span><b>{file ? file.name : "Choose a CSV file"}</b><small>{file ? `${(file.size / 1024).toFixed(1)} KB` : `UTF-8 CSV · E.164 phone · language codes: ${languages.join(", ")}`}</small></label><p className="language-hint">Mock mode runs real ElevenLabs Agent Testing conversations, but never calls the uploaded phone numbers. Contact responses are independently generated; concurrent simulations follow the API MAX_CONCURRENT setting.</p><a className="sample-link" href="/sample-contacts.csv" download>Download sample contact list</a></section>
      {error && <div className="error-panel">{error}</div>}<div className="form-actions"><Link className="text-button" href="/campaigns">Cancel</Link><button className="primary-button" disabled={busy || languages.length === 0}>{busy ? "Creating…" : "Create campaign →"}</button></div>
    </form>
  </div></Shell>;
}
