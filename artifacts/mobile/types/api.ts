export interface DashboardData {
  timestamp: string;
  trading_mode: string;
  executor: {
    mode: string;
    total_trades?: number;
    winning_trades?: number;
    total_pnl?: number;
    today_pnl?: number;
  };
  positions: {
    open: OpenPosition[];
    tracker: {
      tracked_positions: number;
      total_unrealized_pnl: number;
    };
  };
  capital: number;
  risk_limits: {
    max_daily_loss: number;
    max_trade_risk_pct: number;
    max_open_positions: number;
    vix_halt_threshold: number;
  };
}

export interface OpenPosition {
  trade_id: string;
  symbol: string;
  underlying: string;
  direction: string;
  entry_price: number;
  quantity: number;
  current_price?: number;
  unrealized_pnl?: number;
}

export interface Trade {
  trade_id: string;
  symbol: string;
  underlying: string;
  direction: string;
  entry_price: number;
  sl_price: number;
  target_price: number;
  exit_price: number | null;
  quantity: number;
  status: "OPEN" | "CLOSED" | "CANCELLED" | string;
  pnl: number | null;
  current_price?: number;
  unrealized_pnl?: number;
  exit_reason: string | null;
  consensus_score: number | null;
  trade_type: string;
  entry_time: string | null;
  exit_time: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentVote {
  agent_id: string;
  direction: string;
  confidence: number;
  weight: number;
  weighted_score: number;
  reasoning: string;
  supporting_data: Record<string, unknown> | null;
  voted_at: string;
}

export interface TradeDetail {
  trade: Trade;
  agent_votes: AgentVote[];
  trade_log: TradeLogEntry[];
}

export interface TradeLogEntry {
  event: string;
  status: string;
  price: number | null;
  quantity: number | null;
  pnl: number | null;
  agent_votes: Record<string, unknown> | null;
  consensus_score: number | null;
  risk_approval: boolean | null;
  risk_reasoning: string | null;
  details: Record<string, unknown> | null;
  timestamp: string;
}

export interface AgentStatus {
  source: string;
  event_type: string;
  message: string;
  details: Record<string, unknown> | null;
  timestamp: string;
}

export interface Signal {
  id: number;
  agent_id: string;
  timestamp: string;
  underlying: string;
  direction: string;
  confidence: number;
  timeframe: string;
  reasoning: string;
  supporting_data: Record<string, unknown> | null;
  created_at: string;
}

export interface NewsItem {
  id: number;
  event_type: string;
  source: string;
  message: string;
  details: Record<string, unknown> | null;
  timestamp: string;
}

export interface Settings {
  trading_mode: string;
  instruments: string[];
  capital: number;
  max_daily_loss: number;
  max_trade_risk_pct: number;
  max_open_positions: number;
  vix_halt_threshold: number;
  consensus_threshold: number;
}

export interface TickData {
  symbol: string;
  ltp: number;
  volume?: number;
  oi?: number;
  change_pct?: number;
  timestamp: string;
}

export interface WSMessage {
  type: string;
  data: unknown;
  timestamp: string;
}

export interface ZerodhaStatus {
  authenticated: boolean;
  user_id?: string;
  user_name?: string;
  broker?: string;
  message?: string;
}
