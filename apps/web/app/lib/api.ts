export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Script = { language: string; first_message: string; voicemail_message: string; key_points: string; approved: boolean };
export type Summary = { total_contacts: number; completed_calls: number; retryable_contacts: number; outcomes: Record<string, number>; by_language: Record<string, Record<string, number>>; by_segment: Record<string, Record<string, number>> };
export type Campaign = { id: string; name: string; template_id: string; fields: Record<string, string>; languages: string[]; status: "draft" | "ready" | "running" | "done"; created_at: string; contact_count: number; approved: boolean; scripts: Script[]; summary: Summary };
export type CallRecord = { id: string; user_id: string; name: string; phone: string; language: string; segment: string; attempt: number; state: string; outcome: string | null; input_mode: string | null; duration_s: number | null; callback_time: string | null; exact_response: string | null; transcript_redacted: string | null };

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...init, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const languageNames: Record<string, string> = {
  ar: "Arabic", bg: "Bulgarian", zh: "Chinese", hr: "Croatian", cs: "Czech",
  da: "Danish", nl: "Dutch", en: "English", fil: "Filipino", fi: "Finnish",
  fr: "French", de: "German", el: "Greek", hi: "Hindi", hu: "Hungarian",
  id: "Indonesian", it: "Italian", ja: "Japanese", ko: "Korean", ms: "Malay",
  no: "Norwegian", pl: "Polish", pt: "Portuguese", ro: "Romanian", ru: "Russian",
  sk: "Slovak", es: "Spanish", sv: "Swedish", ta: "Tamil", tr: "Turkish",
  uk: "Ukrainian", ml: "Malayalam",
};
export const outcomeNames: Record<string, string> = { confirmed: "Confirmed", declined: "Declined", maybe: "Unsure / conditional", callback: "Callback requested", no_answer: "No answer", voicemail: "Voicemail", failed: "Failed", queued: "Pending", dialing: "In progress", optout: "Opted out", other: "Other response" };
