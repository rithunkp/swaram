export type SupervisorCampaign = {
  campaign_id: string;
  campaign_name: string;
  status: string;
  contact_count: number;
  attempted_contacts: number;
  active_contacts: number;
  completed_contacts: number;
  retryable_contacts: number;
  open_review_candidates: number;
  average_duration_s: number | null;
  response_rate: number | null;
  outcomes: Record<string, number>;
  by_language: Record<string, { contacts: number; completed: number; confirmed: number; response_rate: number | null }>;
  by_segment: Record<string, Record<string, number>>;
  recommendations: string[];
  llm_insights: string[];
  observed_at: string;
};

export type ReviewItem = {
  id: string;
  campaign_id: string;
  campaign_name: string;
  call_id: string;
  language: string;
  segment: string;
  outcome: string;
  attempt: number;
  kind: string;
  reason: string;
  status: string;
  created_at: string;
};

export type SupervisorOverview = {
  connected: boolean;
  last_error?: string | null;
  last_sync?: string | null;
  analysis_mode: string;
  auto_retry: boolean;
  max_attempts: number;
  campaigns: SupervisorCampaign[];
  open_review_count: number;
};

const baseUrl = process.env.NEXT_PUBLIC_SUPERVISOR_API_URL ?? "http://localhost:8100";

export async function supervisorApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Supervisor API error (${response.status})`);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
