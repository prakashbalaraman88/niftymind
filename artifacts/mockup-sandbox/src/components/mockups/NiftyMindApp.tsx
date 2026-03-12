import { useState } from "react";
import {
  TrendingUp, RefreshCw, Activity, Layers, GitBranch, Rss,
  Eye, Zap, BarChart2, Clock, Shield, Users, ArrowUpRight,
  ArrowDownRight, ChevronDown, ChevronUp, FileText, Calendar,
  Settings, LayoutDashboard, List,
} from "lucide-react";

// ─── Design tokens (mirrors mobile constants/colors.ts) ──────────────────────
const C = {
  bg: "#070709",
  surface: "#0F1014",
  elevated: "#16181E",
  card: "#1A1C24",
  cardBorder: "rgba(255,255,255,0.07)",
  text: "#FFFFFF",
  textSecondary: "rgba(255,255,255,0.55)",
  textTertiary: "rgba(255,255,255,0.30)",
  accent: "#8B5CF6",
  accentLight: "rgba(124,58,237,0.15)",
  green: "#10F0A0",
  greenDark: "rgba(16,240,160,0.12)",
  greenGlow: "rgba(16,240,160,0.25)",
  red: "#FF3B5C",
  redDark: "rgba(255,59,92,0.12)",
  gold: "#FFB800",
  goldDark: "rgba(255,184,0,0.12)",
  separator: "rgba(255,255,255,0.05)",
};

// ─── Mock data ────────────────────────────────────────────────────────────────
const MOCK = {
  pnl: 18450,
  pnlPct: 3.69,
  capital: 500000,
  openPositions: 2,
  totalTrades: 7,
  nifty: { price: 24187.5, change: 0.84 },
  bankNifty: { price: 51934.2, change: -0.31 },
  vix: { value: 13.42, halt: 25 },
  mode: "paper" as const,
};

const AGENTS = [
  { id: "agent_1_options_chain", name: "Options Chain", short: "Options", icon: TrendingUp, dir: "BULLISH", conf: 0.82, tf: "INTRADAY", reasoning: "PCR 1.41 (contrarian bullish). Max pain 24200 — spot below, strong upward magnetic pull. Call OI at 24300 CE building with strike delta 0.44.", underlying: "NIFTY" },
  { id: "agent_2_order_flow", name: "Order Flow", short: "Flow", icon: RefreshCw, dir: "BULLISH", conf: 0.77, tf: "SCALP", reasoning: "Buy pressure 64%, delta +1240. Bid absorptions 8 vs ask absorptions 3. Large lots — Buy: 4, Sell: 1.", underlying: "NIFTY" },
  { id: "agent_3_volume_profile", name: "Volume Profile", short: "Vol", icon: Activity, dir: "BULLISH", conf: 0.71, tf: "INTRADAY", reasoning: "Spot above VWAP ₹24,145. POC: 24100 acting as support. High-volume node at 24150–24200 confluence.", underlying: "NIFTY" },
  { id: "agent_4_technical", name: "Technical", short: "Tech", icon: Layers, dir: "BULLISH", conf: 0.74, tf: "INTRADAY", reasoning: "EMA9 > EMA21 > EMA50 aligned. CPR: PP 24155, TC 24210 as next target. RSI 57 — no divergence.", underlying: "NIFTY" },
  { id: "agent_5_sentiment", name: "Sentiment", short: "Sent", icon: GitBranch, dir: "BULLISH", conf: 0.68, tf: "INTRADAY", reasoning: "FII net +₹2,340 Cr (strong institutional buying). A/D ratio 1.68 (breadth positive). VIX 13.42 — low fear.", underlying: "NIFTY" },
  { id: "agent_6_news", name: "News Sentinel", short: "News", icon: Rss, dir: "NEUTRAL", conf: 0.40, tf: "INTRADAY", reasoning: "No Tier-1 events today. RBI policy next week. US PCE data tonight — minor risk window 9:00 PM IST.", underlying: "NIFTY" },
  { id: "agent_7_macro", name: "Global Macro", short: "Macro", icon: Eye, dir: "BULLISH", conf: 0.63, tf: "INTRADAY", reasoning: "S&P 500 futures +0.6% → Nifty +0.2–0.27% expected. Crude $72.4 (neutral zone). DXY 104.1 stable. SGX Nifty +48 pts.", underlying: "NIFTY" },
  { id: "agent_8_scalp", name: "Scalp Decision", short: "Scalp", icon: Zap, dir: "BULLISH", conf: 0.71, tf: "SCALP", reasoning: "Agents 1+2+3 aligned BULLISH. Consensus score 0.74. Entry: NIFTY 24200 CE. 2 lots. SL ₹12, Target ₹28.", underlying: "NIFTY" },
  { id: "agent_9_intraday", name: "Intraday Decision", short: "Intra", icon: BarChart2, dir: "BULLISH", conf: 0.79, tf: "INTRADAY", reasoning: "6/7 agents BULLISH. Weighted score 0.76. Strike 24250 CE, 3 lots, SL 15%, target 30%. Time window: 10:15–12:30.", underlying: "NIFTY" },
  { id: "agent_10_btst", name: "BTST Decision", short: "BTST", icon: Clock, dir: "NEUTRAL", conf: 0.30, tf: "BTST", reasoning: "Too early for BTST analysis. Window opens 14:30 IST. US futures data incomplete.", underlying: "NIFTY" },
  { id: "agent_11_risk", name: "Risk Manager", short: "Risk", icon: Shield, dir: "NEUTRAL", conf: 0.90, tf: "INTRADAY", reasoning: "Daily P&L +₹18,450 (3.69%). 2 open positions. VIX 13.42 — below halt threshold. Risk APPROVED.", underlying: "NIFTY" },
  { id: "agent_12_consensus", name: "Consensus Engine", short: "Concn", icon: Users, dir: "BULLISH", conf: 0.76, tf: "INTRADAY", reasoning: "Weighted score 0.76 (threshold 0.65). Bull votes: 6, Neutral: 1. Firing trade proposal → Decision agents.", underlying: "NIFTY" },
];

const TRADES = [
  { id: "TRD-001", symbol: "NIFTY24MAR24250CE", dir: "BULLISH", type: "BUY", qty: 3, entry: 87.5, exit: 124.0, sl: 74.0, target: 118.0, status: "CLOSED", pnl: 5475, consensus: 0.79, exitReason: "Target hit at 11:42 IST" },
  { id: "TRD-002", symbol: "BANKNIFTY24MAR52000PE", dir: "BEARISH", type: "BUY", qty: 1, entry: 145.0, exit: 98.0, sl: 168.0, target: 95.0, status: "CLOSED", pnl: -4700, consensus: 0.61, exitReason: "SL triggered at 10:08 IST" },
  { id: "TRD-003", symbol: "NIFTY24MAR24200CE", dir: "BULLISH", type: "BUY", qty: 2, entry: 112.0, exit: null, sl: 95.0, target: 148.0, status: "OPEN", pnl: 2400, consensus: 0.74, exitReason: null },
  { id: "TRD-004", symbol: "NIFTY24MAR24150CE", dir: "BULLISH", type: "BUY", qty: 3, entry: 78.5, exit: 114.5, sl: 66.0, target: 112.0, status: "CLOSED", pnl: 5400, consensus: 0.77, exitReason: "Target hit at 14:15 IST" },
  { id: "TRD-005", symbol: "NIFTY24MAR24300CE", dir: "BULLISH", type: "BUY", qty: 2, entry: 34.0, exit: null, sl: 26.0, target: 58.0, status: "OPEN", pnl: 1800, consensus: 0.71, exitReason: null },
];

const NEWS = [
  { id: 1, type: "event", headline: "RBI Monetary Policy Committee Meeting", source: "NSE Economic Calendar", impact: "high", eventTime: "10:00 AM IST, Next Tuesday" },
  { id: 2, type: "event", headline: "US Non-Farm Payrolls (Feb)", source: "Fed Reserve", impact: "high", eventTime: "9:30 PM IST, Tonight" },
  { id: 3, type: "event", headline: "India CPI Inflation Data", source: "MOSPI", impact: "medium", eventTime: "5:30 PM IST, Tomorrow" },
  { id: 4, type: "news", headline: "FIIs pump ₹2,340 Cr into Indian equities — IT & Banking sectors see strong inflows", source: "MoneyControl", impact: "positive", time: "2m ago" },
  { id: 5, type: "news", headline: "Nifty Bank outperforms amid rate-cut hopes; HDFC Bank, SBI gain 1.2–1.8%", source: "ET Markets", impact: "positive", time: "18m ago" },
  { id: 6, type: "news", headline: "US Fed minutes signal caution on rate cuts — markets digest higher-for-longer narrative", source: "Reuters", impact: "mixed", time: "1h ago" },
  { id: 7, type: "news", headline: "Crude oil slips to $72.4/bbl on inventory build; positive for import-heavy Indian markets", source: "LiveMint", impact: "positive", time: "2h ago" },
  { id: 8, type: "news", headline: "Sensex, Nifty consolidate gains near record highs; IT stocks drag on muted guidance", source: "CNBC TV18", impact: "medium", time: "3h ago" },
];

// ─── Component helpers ────────────────────────────────────────────────────────

function Badge({ label, variant }: { label: string; variant: string }) {
  const map: Record<string, { bg: string; color: string; border: string }> = {
    bullish:  { bg: "rgba(16,240,160,0.12)", color: "#10F0A0", border: "rgba(16,240,160,0.25)" },
    bearish:  { bg: "rgba(255,59,92,0.12)",  color: "#FF3B5C", border: "rgba(255,59,92,0.25)" },
    neutral:  { bg: "rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.55)", border: "rgba(255,255,255,0.12)" },
    paper:    { bg: "rgba(124,58,237,0.15)", color: "#8B5CF6", border: "rgba(124,58,237,0.3)" },
    live:     { bg: "rgba(255,184,0,0.12)", color: "#FFB800", border: "rgba(255,184,0,0.3)" },
    high:     { bg: "rgba(255,59,92,0.12)",  color: "#FF3B5C", border: "rgba(255,59,92,0.25)" },
    medium:   { bg: "rgba(255,184,0,0.12)",  color: "#FFB800", border: "rgba(255,184,0,0.3)" },
    low:      { bg: "rgba(16,240,160,0.08)", color: "#10F0A0", border: "rgba(16,240,160,0.2)" },
    positive: { bg: "rgba(16,240,160,0.08)", color: "#10F0A0", border: "rgba(16,240,160,0.2)" },
    mixed:    { bg: "rgba(255,184,0,0.12)",  color: "#FFB800", border: "rgba(255,184,0,0.3)" },
    open:     { bg: "rgba(124,58,237,0.15)", color: "#8B5CF6", border: "rgba(124,58,237,0.3)" },
    closed:   { bg: "rgba(16,240,160,0.08)", color: "#10F0A0", border: "rgba(16,240,160,0.2)" },
    cancelled:{ bg: "rgba(255,255,255,0.06)", color: "rgba(255,255,255,0.4)", border: "rgba(255,255,255,0.1)" },
  };
  const s = map[variant.toLowerCase()] || map.neutral;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 8px", borderRadius: 6, fontSize: 10, fontWeight: 600,
      letterSpacing: "0.4px", textTransform: "uppercase",
      background: s.bg, color: s.color, border: `1px solid ${s.border}`,
    }}>
      {label}
    </span>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.cardBorder}`,
      borderRadius: 16,
      padding: 16,
      ...style,
    }}>
      {children}
    </div>
  );
}

function PnlText({ value, size = 15 }: { value: number; size?: number }) {
  const color = value > 0 ? C.green : value < 0 ? C.red : C.textSecondary;
  const sign = value > 0 ? "+" : "";
  return (
    <span style={{ color, fontSize: size, fontWeight: 700, textShadow: value > 0 ? `0 0 12px ${C.greenGlow}` : value < 0 ? `0 0 12px rgba(255,59,92,0.3)` : "none" }}>
      {sign}₹{Math.abs(value).toLocaleString("en-IN")}
    </span>
  );
}

function ConfBar({ value, color }: { value: number; color: string }) {
  return (
    <div style={{ flex: 1, height: 5, background: C.elevated, borderRadius: 3, overflow: "hidden" }}>
      <div style={{ width: `${value * 100}%`, height: "100%", background: color, borderRadius: 3 }} />
    </div>
  );
}

// ─── Tab screens ──────────────────────────────────────────────────────────────

function DashboardScreen() {
  const { pnl, pnlPct, capital, openPositions, totalTrades, nifty, bankNifty, vix, mode } = MOCK;
  const pnlColor = pnl >= 0 ? C.green : C.red;
  const vixPct = Math.min((vix.value / (vix.halt * 1.5)) * 100, 100);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          <div style={{ fontSize: 28, fontWeight: 700, color: C.text, letterSpacing: -1 }}>NiftyMind</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: C.green, boxShadow: `0 0 8px ${C.green}`, display: "inline-block" }} />
            <span style={{ fontSize: 12, color: C.textSecondary }}>Live</span>
            <Badge label={mode} variant={mode} />
          </div>
        </div>
      </div>

      {/* P&L Hero */}
      <div style={{
        background: `linear-gradient(135deg, rgba(16,240,160,0.06) 0%, transparent 60%)`,
        border: `1px solid ${C.cardBorder}`,
        borderRadius: 20,
        padding: "20px 20px 16px",
      }}>
        <div style={{ fontSize: 11, color: C.textSecondary, letterSpacing: 1, textTransform: "uppercase", marginBottom: 6 }}>Today's P&L</div>
        <div style={{ fontSize: 42, fontWeight: 700, color: pnlColor, letterSpacing: -1.5, textShadow: `0 0 24px ${C.greenGlow}`, marginBottom: 2 }}>
          +₹{pnl.toLocaleString("en-IN")}
        </div>
        <div style={{ fontSize: 13, color: C.green, marginBottom: 16 }}>+{pnlPct.toFixed(2)}% return</div>
        <div style={{ display: "flex", borderTop: `1px solid ${C.separator}`, paddingTop: 12, gap: 0 }}>
          {[["Capital", `₹${(capital / 1000).toFixed(0)}K`], ["Open", String(openPositions)], ["Trades", String(totalTrades)]].map(([label, val], i) => (
            <div key={label} style={{ flex: 1, textAlign: "center", borderRight: i < 2 ? `1px solid ${C.separator}` : "none" }}>
              <div style={{ fontSize: 11, color: C.textTertiary, marginBottom: 3 }}>{label}</div>
              <div style={{ fontSize: 15, fontWeight: 600, color: C.text }}>{val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Price Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        {[
          { label: "NIFTY 50", ...nifty },
          { label: "BANKNIFTY", price: bankNifty.price, change: bankNifty.change },
        ].map(({ label, price, change }) => (
          <Card key={label}>
            <div style={{ fontSize: 10, color: C.textSecondary, letterSpacing: 0.5, marginBottom: 6, textTransform: "uppercase" }}>{label}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: C.text, letterSpacing: -0.5 }}>
              {price.toLocaleString("en-IN", { maximumFractionDigits: 1 })}
            </div>
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 3, marginTop: 8,
              padding: "3px 7px", borderRadius: 6,
              background: change >= 0 ? C.greenDark : C.redDark,
            }}>
              {change >= 0
                ? <ArrowUpRight size={11} color={C.green} />
                : <ArrowDownRight size={11} color={C.red} />}
              <span style={{ fontSize: 11, fontWeight: 600, color: change >= 0 ? C.green : C.red }}>
                {Math.abs(change).toFixed(2)}%
              </span>
            </div>
          </Card>
        ))}
      </div>

      {/* VIX Card */}
      <Card>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ width: 34, height: 34, borderRadius: 10, background: C.greenDark, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Activity size={14} color={C.green} />
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: C.text }}>India VIX</div>
              <div style={{ fontSize: 11, color: C.textTertiary }}>Volatility Index</div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 22, fontWeight: 700, color: C.text }}>{vix.value.toFixed(2)}</span>
            <Badge label="OK" variant="low" />
          </div>
        </div>
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: C.textTertiary, marginBottom: 5 }}>Halt at {vix.halt}</div>
          <div style={{ height: 5, background: C.elevated, borderRadius: 3, position: "relative", overflow: "hidden" }}>
            <div style={{ width: `${vixPct}%`, height: "100%", background: C.green, borderRadius: 3 }} />
            <div style={{
              position: "absolute", top: -3, left: `${(vix.halt / (vix.halt * 1.5)) * 100}%`,
              width: 2, height: 11, background: C.red, borderRadius: 1,
            }} />
          </div>
        </div>
      </Card>

      {/* Agent Grid */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: C.text }}>Agent Grid</span>
          <span style={{ fontSize: 11, fontWeight: 600, color: C.accent, background: C.accentLight, borderRadius: 8, padding: "2px 8px" }}>12 AI</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
          {AGENTS.map((a) => {
            const Icon = a.icon;
            const dirColor = a.dir === "BULLISH" ? C.green : a.dir === "BEARISH" ? C.red : C.textTertiary;
            return (
              <div key={a.id} style={{
                background: C.card, border: `1px solid ${C.cardBorder}`,
                borderRadius: 14, padding: "10px 8px", display: "flex", flexDirection: "column",
                alignItems: "center", gap: 4, position: "relative",
              }}>
                <span style={{
                  position: "absolute", top: 7, right: 7, width: 6, height: 6, borderRadius: "50%",
                  background: a.dir !== "NEUTRAL" ? C.green : C.textTertiary,
                  boxShadow: a.dir !== "NEUTRAL" ? `0 0 6px ${C.green}` : "none",
                }} />
                <Icon size={15} color={dirColor} />
                <span style={{ fontSize: 9, fontWeight: 500, color: C.textSecondary, textAlign: "center" }}>{a.short}</span>
                <span style={{ fontSize: 9, fontWeight: 600, color: dirColor }}>
                  {a.dir === "BULLISH" ? "BULL" : a.dir === "BEARISH" ? "BEAR" : "--"}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Open Positions */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: C.text }}>Open Positions</span>
          <span style={{ fontSize: 13, color: C.textSecondary }}>{openPositions} active</span>
        </div>
        {TRADES.filter(t => t.status === "OPEN").map(t => (
          <Card key={t.id} style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{t.symbol}</div>
                <div style={{ fontSize: 11, color: C.textSecondary, marginTop: 2 }}>
                  {t.dir} · {t.qty} lots @ ₹{t.entry}
                </div>
              </div>
              <PnlText value={t.pnl} size={14} />
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

function AgentsScreen() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {AGENTS.map((a) => {
        const Icon = a.icon;
        const dirColor = a.dir === "BULLISH" ? C.green : a.dir === "BEARISH" ? C.red : C.accent;
        const iconBg = a.dir === "BULLISH"
          ? "linear-gradient(135deg, #10F0A0, #22D47A)"
          : a.dir === "BEARISH"
          ? "linear-gradient(135deg, #FF3B5C, #FF6B81)"
          : "linear-gradient(135deg, #7C3AED, #2563EB)";
        const isStale = a.id === "agent_10_btst";
        return (
          <Card key={a.id} style={{ opacity: isStale ? 0.6 : 1 }}>
            <div style={{ display: "flex", alignItems: "center" }}>
              <div style={{ width: 38, height: 38, borderRadius: 12, background: iconBg, display: "flex", alignItems: "center", justifyContent: "center", marginRight: 12, flexShrink: 0 }}>
                <Icon size={16} color="#fff" />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: C.text }}>{a.name}</div>
                <div style={{ fontSize: 11, color: C.textTertiary }}>{a.id.replace("_", " #")}</div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Badge label={a.dir} variant={a.dir.toLowerCase()} />
                <span style={{
                  width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                  background: isStale ? C.textTertiary : C.green,
                  boxShadow: isStale ? "none" : `0 0 6px ${C.green}`,
                }} />
              </div>
            </div>
            <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${C.separator}` }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
                <span style={{ fontSize: 11, color: C.textTertiary, width: 75 }}>Confidence</span>
                <ConfBar value={a.conf} color={dirColor} />
                <span style={{ fontSize: 11, fontWeight: 700, color: dirColor, width: 34, textAlign: "right" }}>
                  {(a.conf * 100).toFixed(0)}%
                </span>
              </div>
              <div style={{ display: "flex", gap: 16, marginBottom: 7 }}>
                <div><span style={{ fontSize: 11, color: C.textTertiary }}>Underlying: </span><span style={{ fontSize: 11, color: C.text }}>{a.underlying}</span></div>
                <div><span style={{ fontSize: 11, color: C.textTertiary }}>Timeframe: </span><span style={{ fontSize: 11, color: C.text }}>{a.tf}</span></div>
              </div>
              <div style={{ fontSize: 11, color: C.textSecondary, lineHeight: 1.6 }}>{a.reasoning}</div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function TradesScreen() {
  const [filter, setFilter] = useState<"all" | "OPEN" | "CLOSED">("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const filters = [{ k: "all", l: "All" }, { k: "OPEN", l: "Open" }, { k: "CLOSED", l: "Closed" }] as const;
  const trades = filter === "all" ? TRADES : TRADES.filter(t => t.status === filter);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      {/* Filter pills */}
      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        {filters.map(f => (
          <button key={f.k} onClick={() => setFilter(f.k)} style={{
            padding: "7px 16px", borderRadius: 20, border: "none", cursor: "pointer",
            background: filter === f.k ? "linear-gradient(90deg,#7C3AED,#2563EB)" : C.card,
            color: filter === f.k ? "#fff" : C.textSecondary,
            fontSize: 13, fontWeight: filter === f.k ? 600 : 500,
            outline: filter === f.k ? "none" : `1px solid ${C.cardBorder}`,
          }}>
            {f.l}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {trades.map((t) => {
          const isOpen = t.status === "OPEN";
          const isProfit = (t.pnl ?? 0) > 0;
          const isClosed = t.status === "CLOSED";
          const isExp = expanded === t.id;
          const dirVariant = t.dir.toLowerCase();
          return (
            <Card key={t.id} style={{
              borderColor: isClosed && isProfit ? "rgba(16,240,160,0.15)" : C.cardBorder,
              background: isClosed && isProfit
                ? `linear-gradient(180deg, rgba(16,240,160,0.04) 0%, ${C.card} 100%)`
                : C.card,
              padding: "14px 14px 12px",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", cursor: "pointer" }}
                onClick={() => setExpanded(isExp ? null : t.id)}>
                <div style={{ flex: 1, marginRight: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>{t.symbol}</span>
                    <Badge label={t.dir} variant={dirVariant} />
                  </div>
                  <div style={{ fontSize: 12, color: C.textSecondary }}>
                    {t.type} · {t.qty} lots ·{" "}
                    <span style={{ color: isOpen ? C.accent : isClosed && isProfit ? C.green : C.textTertiary }}>
                      {t.status}
                    </span>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <PnlText value={t.pnl ?? 0} size={14} />
                  {isExp ? <ChevronUp size={16} color={C.textTertiary} /> : <ChevronDown size={16} color={C.textTertiary} />}
                </div>
              </div>
              {isExp && (
                <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${C.separator}` }}>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
                    {[["Entry", `₹${t.entry}`, ""], ["SL", `₹${t.sl}`, C.red], ["Target", `₹${t.target}`, C.green], ...(t.exit ? [["Exit", `₹${t.exit}`, ""]] : [])].map(([label, val, col]) => (
                      <div key={label} style={{ background: C.elevated, borderRadius: 10, padding: "8px 12px" }}>
                        <div style={{ fontSize: 10, color: C.textTertiary, marginBottom: 2 }}>{label}</div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: col || C.text }}>{val}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <span style={{ fontSize: 12, color: C.textSecondary, width: 80 }}>Consensus</span>
                    <ConfBar value={t.consensus} color={C.accent} />
                    <span style={{ fontSize: 12, fontWeight: 700, color: C.accent, width: 34, textAlign: "right" }}>
                      {(t.consensus * 100).toFixed(0)}%
                    </span>
                  </div>
                  {t.exitReason && (
                    <div style={{ fontSize: 12, color: C.textSecondary }}>{t.exitReason}</div>
                  )}
                  <div style={{ fontSize: 11, fontWeight: 600, color: C.textTertiary, marginTop: 10, marginBottom: 6, letterSpacing: 0.5 }}>AGENT VOTES</div>
                  {AGENTS.slice(0, 7).map(a => {
                    const Icon = a.icon;
                    const dc = a.dir === "BULLISH" ? C.green : a.dir === "BEARISH" ? C.red : C.textSecondary;
                    return (
                      <div key={a.id} style={{ display: "flex", alignItems: "center", padding: "7px 0", borderBottom: `1px solid ${C.separator}` }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flex: 1 }}>
                          <Icon size={13} color={dc} />
                          <span style={{ fontSize: 12, fontWeight: 500, color: C.text }}>{a.name}</span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div style={{ width: 44, height: 4, background: C.elevated, borderRadius: 2, overflow: "hidden" }}>
                            <div style={{ width: `${a.conf * 100}%`, height: "100%", background: dc, borderRadius: 2 }} />
                          </div>
                          <span style={{ fontSize: 10, fontWeight: 600, color: dc, width: 30, textAlign: "right" }}>
                            {a.dir.substring(0, 4)}
                          </span>
                          <span style={{ fontSize: 11, color: C.textSecondary, width: 28, textAlign: "right" }}>
                            {(a.conf * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function NewsScreen() {
  const events = NEWS.filter(n => n.type === "event");
  const news = NEWS.filter(n => n.type === "news");
  const impactVariant = (imp: string) =>
    imp === "high" || imp === "negative" ? "high" : imp === "medium" || imp === "mixed" ? "medium" : "low";

  const SectionHeader = ({ title, count }: { title: string; count: number }) => (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 0 10px" }}>
      <span style={{ fontSize: 16, fontWeight: 600, color: C.text }}>{title}</span>
      <span style={{ fontSize: 12, fontWeight: 500, color: C.textSecondary, background: C.elevated, borderRadius: 10, padding: "2px 8px" }}>{count}</span>
    </div>
  );

  return (
    <div>
      <SectionHeader title="Upcoming Events" count={events.length} />
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {events.map(item => (
          <Card key={item.id} style={{ borderColor: item.impact === "high" ? "rgba(255,59,92,0.12)" : item.impact === "medium" ? "rgba(255,184,0,0.12)" : C.cardBorder }}>
            <div style={{ display: "flex", alignItems: "flex-start" }}>
              <div style={{ width: 34, height: 34, borderRadius: 10, background: "rgba(255,184,0,0.15)", display: "flex", alignItems: "center", justifyContent: "center", marginRight: 12, flexShrink: 0 }}>
                <Calendar size={15} color={C.gold} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 500, color: C.text, lineHeight: 1.4, marginBottom: 6 }}>{item.headline}</div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 11, color: C.textSecondary }}>{item.source}</span>
                  <Badge label={item.impact} variant={impactVariant(item.impact)} />
                </div>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 10, paddingTop: 10, borderTop: `1px solid ${C.separator}` }}>
              <Clock size={11} color={C.gold} />
              <span style={{ fontSize: 12, fontWeight: 600, color: C.gold }}>{item.eventTime}</span>
            </div>
          </Card>
        ))}
      </div>

      <SectionHeader title="Market News" count={news.length} />
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {news.map(item => (
          <Card key={item.id} style={{ borderColor: item.impact === "high" ? "rgba(255,59,92,0.12)" : item.impact === "mixed" ? "rgba(255,184,0,0.12)" : C.cardBorder }}>
            <div style={{ display: "flex", alignItems: "flex-start" }}>
              <div style={{ width: 34, height: 34, borderRadius: 10, background: "rgba(124,58,237,0.15)", display: "flex", alignItems: "center", justifyContent: "center", marginRight: 12, flexShrink: 0 }}>
                <FileText size={15} color={C.accent} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 500, color: C.text, lineHeight: 1.4, marginBottom: 6 }}>{item.headline}</div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 11, color: C.textSecondary }}>{item.source}</span>
                  <Badge label={item.impact} variant={impactVariant(item.impact)} />
                </div>
              </div>
            </div>
            <div style={{ fontSize: 11, color: C.textTertiary, marginTop: 8, textAlign: "right" }}>{(item as any).time}</div>
          </Card>
        ))}
      </div>
    </div>
  );
}

function SettingsScreen() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <Card>
        <div style={{ fontSize: 12, fontWeight: 600, color: C.textTertiary, letterSpacing: 1, marginBottom: 12 }}>TRADING MODE</div>
        <div style={{ display: "flex", gap: 8 }}>
          {["paper", "live"].map(m => (
            <button key={m} style={{
              flex: 1, padding: "10px", borderRadius: 12, border: "none", cursor: "pointer",
              background: m === "paper" ? "linear-gradient(90deg,#7C3AED,#2563EB)" : C.elevated,
              color: m === "paper" ? "#fff" : C.textSecondary,
              fontSize: 13, fontWeight: 600, textTransform: "capitalize",
            }}>
              {m === "live" ? "🔴 " : ""}{m.charAt(0).toUpperCase() + m.slice(1)}
            </button>
          ))}
        </div>
        <div style={{ fontSize: 12, color: C.textTertiary, marginTop: 10 }}>Live mode requires PIN verification and active Zerodha session.</div>
      </Card>

      <Card>
        <div style={{ fontSize: 12, fontWeight: 600, color: C.textTertiary, letterSpacing: 1, marginBottom: 12 }}>RISK PARAMETERS</div>
        {[["Capital", "₹5,00,000"], ["Max Daily Loss", "₹25,000 (5%)"], ["Max Trade Risk", "2% per trade"], ["Max Open Positions", "3"], ["VIX Halt Threshold", "25"]].map(([label, val]) => (
          <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: `1px solid ${C.separator}` }}>
            <span style={{ fontSize: 14, color: C.text }}>{label}</span>
            <span style={{ fontSize: 14, fontWeight: 600, color: C.accent }}>{val}</span>
          </div>
        ))}
      </Card>

      <Card>
        <div style={{ fontSize: 12, fontWeight: 600, color: C.textTertiary, letterSpacing: 1, marginBottom: 12 }}>INSTRUMENTS</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {["NIFTY", "BANKNIFTY"].map(inst => (
            <div key={inst} style={{ padding: "8px 16px", borderRadius: 20, background: "linear-gradient(90deg,#7C3AED,#2563EB)", color: "#fff", fontSize: 13, fontWeight: 600 }}>
              {inst}
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <div style={{ fontSize: 12, fontWeight: 600, color: C.textTertiary, letterSpacing: 1, marginBottom: 12 }}>AI MODEL</div>
        {[["Decision Agents", "Claude Sonnet 4.6 + Extended Thinking"], ["Analysis Agents", "Gemini 3 Flash"], ["Thinking Budget", "8,000 tokens"]].map(([label, val]) => (
          <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: `1px solid ${C.separator}` }}>
            <span style={{ fontSize: 13, color: C.textSecondary }}>{label}</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: C.text, textAlign: "right", maxWidth: "55%" }}>{val}</span>
          </div>
        ))}
      </Card>
    </div>
  );
}

// ─── Main App Shell ───────────────────────────────────────────────────────────

const TABS = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "agents", label: "Agents", icon: Users },
  { id: "trades", label: "Trades", icon: List },
  { id: "news", label: "News", icon: Rss },
  { id: "settings", label: "Settings", icon: Settings },
] as const;

type TabId = typeof TABS[number]["id"];

export default function NiftyMindApp() {
  const [tab, setTab] = useState<TabId>("dashboard");

  const screens: Record<TabId, React.ReactNode> = {
    dashboard: <DashboardScreen />,
    agents: <AgentsScreen />,
    trades: <TradesScreen />,
    news: <NewsScreen />,
    settings: <SettingsScreen />,
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: "#111",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "24px 16px 40px",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    }}>
      {/* Phone frame */}
      <div style={{
        width: 390,
        minHeight: 844,
        background: C.bg,
        borderRadius: 48,
        overflow: "hidden",
        position: "relative",
        boxShadow: "0 40px 120px rgba(0,0,0,0.8), 0 0 0 1px rgba(255,255,255,0.1), inset 0 0 0 1px rgba(255,255,255,0.05)",
        display: "flex",
        flexDirection: "column",
      }}>
        {/* Status bar */}
        <div style={{ height: 44, background: C.bg, display: "flex", alignItems: "center", padding: "0 24px", justifyContent: "space-between" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>9:41</span>
          <div style={{ width: 120, height: 32, background: "#000", borderRadius: 20, position: "absolute", left: "50%", transform: "translateX(-50%)", top: 0 }} />
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <div style={{ display: "flex", gap: 2 }}>
              {[4, 7, 10, 13].map(h => <div key={h} style={{ width: 3, height: h, background: C.text, borderRadius: 1 }} />)}
            </div>
            <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>100%</span>
          </div>
        </div>

        {/* Scrollable content */}
        <div style={{ flex: 1, overflowY: "auto", padding: "12px 20px 120px", scrollbarWidth: "none" }}>
          {screens[tab]}
        </div>

        {/* Tab bar */}
        <div style={{
          position: "absolute", bottom: 0, left: 0, right: 0,
          height: 82,
          background: "rgba(7,7,9,0.92)",
          backdropFilter: "blur(20px)",
          borderTop: `1px solid ${C.separator}`,
          display: "flex",
          alignItems: "flex-start",
          paddingTop: 10,
          paddingBottom: 20,
        }}>
          {TABS.map(({ id, label, icon: Icon }) => {
            const active = tab === id;
            return (
              <button key={id} onClick={() => setTab(id)} style={{
                flex: 1, display: "flex", flexDirection: "column", alignItems: "center",
                gap: 4, background: "none", border: "none", cursor: "pointer",
                padding: 0, position: "relative",
              }}>
                {active && (
                  <span style={{
                    position: "absolute", top: -10, width: 48, height: 36,
                    borderRadius: 12,
                    background: C.accentLight,
                    left: "50%", transform: "translateX(-50%)",
                  }} />
                )}
                <Icon size={22} color={active ? C.accent : C.textTertiary} style={{ position: "relative" }} />
                <span style={{ fontSize: 10, fontWeight: active ? 600 : 400, color: active ? C.accent : C.textTertiary, position: "relative" }}>
                  {label}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
