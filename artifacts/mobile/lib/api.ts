import type {
  DashboardData,
  Trade,
  TradeDetail,
  AgentStatus,
  Signal,
  NewsItem,
  Settings,
  ZerodhaStatus,
} from "@/types/api";
import { supabase } from "@/lib/supabase";

const getBaseUrl = (): string => {
  const domain = process.env.EXPO_PUBLIC_DOMAIN;
  if (domain) {
    return `https://${domain}`;
  }
  return "http://localhost:8000";
};

const BASE_URL = getBaseUrl();
const API_PREFIX = `${BASE_URL}/api`;

async function getAuthHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  try {
    const { data } = await supabase.auth.getSession();
    if (data.session?.access_token) {
      headers["Authorization"] = `Bearer ${data.session.access_token}`;
    }
  } catch {
    // Continue without auth header if session retrieval fails
  }
  return headers;
}

async function fetchJson<T>(path: string): Promise<T> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${API_PREFIX}${path}`, {
    headers: { ...authHeaders },
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

async function postJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${API_PREFIX}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `API error ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getDashboard: () => fetchJson<DashboardData>("/dashboard"),

  getTrades: (limit = 50, offset = 0, status?: string) => {
    let url = `/trades?limit=${limit}&offset=${offset}`;
    if (status) url += `&status=${status}`;
    return fetchJson<{ trades: Trade[]; total: number }>(url);
  },

  getTradeDetail: (tradeId: string) =>
    fetchJson<TradeDetail>(`/trades/${tradeId}`),

  closeTrade: (tradeId: string) =>
    postJson<{ status: string; trade_id: string }>(`/trades/${tradeId}/close`, {}),

  getAgents: () => fetchJson<{ agents: AgentStatus[] }>("/agents"),

  getSignals: (limit = 50, agentId?: string) => {
    let url = `/signals?limit=${limit}`;
    if (agentId) url += `&agent_id=${agentId}`;
    return fetchJson<{ signals: Signal[] }>(url);
  },

  getNews: (limit = 20) => fetchJson<{ news: NewsItem[] }>(`/news?limit=${limit}`),

  getSettings: () => fetchJson<Settings>("/settings"),

  updateSettings: (data: Record<string, unknown>) =>
    postJson<{ status: string; applied: Record<string, unknown> }>("/settings", data),

  registerPushToken: (token: string) =>
    postJson<{ status: string }>("/push-token", { token }),

  // ── Zerodha ────────────────────────────────────────────
  getZerodhaLoginUrl: () =>
    fetchJson<{ login_url: string }>("/zerodha/login"),

  getZerodhaStatus: () =>
    fetchJson<ZerodhaStatus>("/zerodha/status"),

  // ── Auth ───────────────────────────────────────────────
  getMe: () =>
    fetchJson<{ user_id: string; email: string; role: string }>("/auth/me"),
};

export const getWsUrl = (): string => {
  const domain = process.env.EXPO_PUBLIC_DOMAIN;
  if (domain) {
    return `wss://${domain}/ws`;
  }
  return "ws://localhost:8000/ws";
};
