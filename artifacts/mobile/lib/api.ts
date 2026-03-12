import type {
  DashboardData,
  Trade,
  TradeDetail,
  AgentStatus,
  Signal,
  NewsItem,
  Settings,
} from "@/types/api";

const getBaseUrl = (): string => {
  const domain = process.env.EXPO_PUBLIC_DOMAIN;
  if (domain) {
    return `https://${domain}`;
  }
  return "http://localhost:8000";
};

const BASE_URL = getBaseUrl();
const API_PREFIX = `${BASE_URL}/api`;

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_PREFIX}${path}`);
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

async function postJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${API_PREFIX}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
};

export const getWsUrl = (): string => {
  const domain = process.env.EXPO_PUBLIC_DOMAIN;
  if (domain) {
    return `wss://${domain}/ws`;
  }
  return "ws://localhost:8000/ws";
};
