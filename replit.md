# Workspace

## Overview

NiftyMind — Multi-Agent AI Options Trading System. A pnpm workspace monorepo (TypeScript) with a Python backend for the trading engine. The system runs 12 specialized AI agents for Nifty 50 and BankNifty options trading.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5 (TypeScript REST/WebSocket API for mobile app)
- **Trading backend**: Python (FastAPI, LangGraph, Redis, Claude API)
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)
- **Data feed**: TrueData WebSocket API (tick-by-tick, options chain)
- **Broker**: Zerodha Kite Connect API
- **AI/LLM**: Anthropic Claude API via LangGraph
- **Message queue**: Redis Pub/Sub

## Structure

```text
artifacts-monorepo/
├── artifacts/              # Deployable applications
│   └── api-server/         # Express API server
├── backend/                # Python trading engine
│   ├── main.py             # Entry point — starts data pipeline
│   ├── config.py           # Configuration from env vars
│   ├── docker-compose.yml  # TimescaleDB + Redis
│   ├── data_pipeline/      # Market data feeds + Redis publisher
│   │   ├── truedata_feed.py
│   │   ├── options_chain_feed.py
│   │   ├── sentiment_feed.py    # NSE FII/DII + market breadth
│   │   ├── news_feed.py         # RSS news + economic calendar
│   │   ├── global_macro_feed.py # Global indices, crude, DXY, yields
│   │   └── redis_publisher.py
│   ├── agents/             # 12 AI agents
│   │   ├── base_agent.py   # Shared lifecycle: market-hours, Redis, signals
│   │   ├── llm_utils.py    # Claude API helper (query_claude)
│   │   ├── options_chain_agent.py      # Agent 1: Options chain analysis (LLM)
│   │   ├── order_flow_agent.py         # Agent 2: Order flow (rule-based)
│   │   ├── volume_profile_agent.py     # Agent 3: Volume profile (rule-based)
│   │   ├── technical_agent.py          # Agent 4: Multi-TF technical (rule-based)
│   │   ├── sentiment_agent.py          # Agent 5: Market sentiment (LLM)
│   │   ├── news_agent.py              # Agent 6: News & events (LLM)
│   │   ├── macro_agent.py             # Agent 7: Global macro (LLM)
│   │   ├── scalping_agent.py          # Agent 8: Scalp decision (rule-based)
│   │   ├── intraday_agent.py          # Agent 9: Intraday decision (LLM)
│   │   ├── btst_agent.py             # Agent 10: BTST decision (LLM)
│   │   ├── risk_manager.py           # Agent 11: Risk validation + veto
│   │   ├── consensus_orchestrator.py  # Agent 12: Weighted vote aggregation
│   │   └── db_logger.py              # PostgreSQL persistence helpers
│   ├── execution/          # Paper + live trade executors
│   │   ├── paper_executor.py    # Simulated fills with slippage, P&L tracking
│   │   ├── kite_executor.py     # Zerodha Kite Connect live execution
│   │   └── position_tracker.py  # SL/target/EOD monitoring + exit triggers
│   └── api/                # FastAPI routes + WebSocket
│       ├── server.py            # FastAPI app factory
│       ├── routes.py            # REST endpoints (dashboard, trades, signals, etc.)
│       └── websocket_handler.py # WS server + Redis relay for live updates
├── lib/                    # Shared libraries
│   ├── api-spec/           # OpenAPI spec + Orval codegen config
│   ├── api-client-react/   # Generated React Query hooks
│   ├── api-zod/            # Generated Zod schemas from OpenAPI
│   └── db/                 # Drizzle ORM schema + DB connection
├── scripts/                # Utility scripts
├── pnpm-workspace.yaml
├── tsconfig.base.json
├── tsconfig.json
└── package.json
```

## Database Schema

Five tables defined in `lib/db/src/schema/`:

- **signals** — Agent analysis signals (direction, confidence, reasoning, supporting data) — TimescaleDB hypertable
- **trades** — Trade lifecycle (entry/exit prices, P&L, status, consensus score)
- **trade_log** — Complete trade event log with agent votes, consensus scores, risk approval per event — TimescaleDB hypertable
- **agent_votes** — Per-agent vote on each trade (direction, confidence, weight, reasoning)
- **audit_logs** — System-wide event log (trade decisions, agent state changes, errors) — TimescaleDB hypertable

TimescaleDB setup: `python backend/setup_timescaledb.py` (requires TimescaleDB extension in Postgres; docker-compose provides it)

## Python Backend (backend/)

The Python trading engine handles:
- Real-time market data ingestion via TrueData WebSocket API
- Redis Pub/Sub for distributing data to agents
- 12 AI agents (7 analysis, 3 decision, 2 control)
- Trade execution (paper + live via Zerodha Kite Connect)

### Data Feeds
- `truedata_feed.py` — TrueData WebSocket for tick-by-tick and OHLC data
- `options_chain_feed.py` — TrueData WebSocket for options chain (Greeks, OI)
- `sentiment_feed.py` — NSE API scraper for FII/DII activity and market breadth (advance/decline)
- `news_feed.py` — RSS feeds (MoneyControl, ET Markets, LiveMint) + economic calendar
- `global_macro_feed.py` — Yahoo Finance for global indices, crude, DXY, USD/INR, US 10Y, gold

### Redis Channels
- `niftymind:ticks` — Raw tick-by-tick data
- `niftymind:options_chain` — Options chain snapshots
- `niftymind:ohlc:{1m,5m,15m}` — OHLC candles
- `niftymind:signals` — Agent signals
- `niftymind:trade_proposals` — Trade proposals from decision agents
- `niftymind:trade_executions` — Executed trade confirmations
- `niftymind:agent_status` — Agent health/state updates
- `niftymind:fii_dii` — FII/DII cash and derivatives activity
- `niftymind:market_breadth` — Advance/decline ratio, breadth data
- `niftymind:news` — Classified financial news articles
- `niftymind:economic_calendar` — Upcoming economic events
- `niftymind:global_macro` — Global indices, crude, DXY, yields, currencies

### Agent Architecture (LangGraph)
- **BaseAgent** (`base_agent.py`): LangGraph StateGraph pipeline with nodes: `gate_check` → `process` → `emit`. Includes market-hours gate (9:15–15:30 IST), expiry-day detection (Thursday), Redis pub/sub subscription, Signal emission, and graceful shutdown.
- **AgentState** (TypedDict): channel, data, should_process, signal, error — flows through the LangGraph graph per message
- **Signal dataclass**: agent_id, timestamp, underlying, direction (BULLISH/BEARISH/NEUTRAL), confidence (0–1), timeframe (SCALP/INTRADAY/BTST), reasoning, supporting_data
- **LLM agents** (1, 5, 6, 7): Use Claude API via `llm_utils.query_claude()` for reasoning
- **Rule-based agents** (2, 3, 4): Pure computation, no LLM calls — optimized for low latency
- All agents handle expiry day (Thursday): agents 2-4 adjust confidence/reasoning on Thursdays, agents 5-7 include it in LLM prompts
- Agent 5 (Sentiment): Subscribes to `fii_dii`, `market_breadth` (including VIX from sentiment_feed); runs market hours + pre-market
- Agent 6 (News): Subscribes to `news`, `economic_calendar`; runs market hours + pre-market
- Agent 7 (Macro): Subscribes to `global_macro` (US futures, crude, DXY, US 10Y, USD/INR, gold, Asian indices); runs market hours + pre-market
- Agent 8 (Scalping Decision): Rule-based, subscribes to `signals`, requires alignment from agents 1-3 (options, order flow, volume)
- Agent 9 (Intraday Decision): LLM-powered, subscribes to `signals`, buffers all 7 analysis signals, proposes intraday options trades
- Agent 10 (BTST Decision): LLM-powered, subscribes to `signals`, runs 14:30-15:25 IST only, proposes overnight positions
- Agent 11 (Risk Manager): Subscribes to `trade_proposals`, `trade_executions`, `market_breadth`; validates against daily loss, open positions, VIX halt, correlation, position sizing; approves or vetoes
- Agent 12 (Consensus Orchestrator): Subscribes to `signals`, aggregates weighted votes per trade type (SCALP/INTRADAY/BTST) with configurable weights, fires proposal when score > threshold

### Decision Pipeline
```
Analysis Signals (1-7) → Consensus Orchestrator (12) → Decision Agents (8-10) → Risk Manager (11) → Trade Executions
```
- Consensus weights per trade type: SCALP emphasizes order flow (0.35) + options (0.25), INTRADAY balanced across all 7, BTST emphasizes macro (0.25) + sentiment (0.25)
- Risk Manager checks: daily loss limit, open position count, VIX halt, correlation risk, capital-at-risk, volatility-adjusted position sizing
- All votes and decisions persisted to PostgreSQL via db_logger.py (agent_votes, trade_log, audit_logs tables)

### Execution Engine
- **Paper Executor** (`paper_executor.py`): Subscribes to `trade_executions` channel, handles RISK_APPROVED events by simulating fills with 0.05% slippage. Tracks open positions, computes P&L on exit. Persists all trades via `upsert_trade` and `log_trade_event`.
- **Kite Executor** (`kite_executor.py`): Live execution via Zerodha Kite Connect. Places MARKET orders on NFO exchange, enforces lot sizes (NIFTY=50, BANKNIFTY=15), resolves weekly expiry trading symbols. Only active in `TRADING_MODE=live`.
- **Position Tracker** (`position_tracker.py`): Monitors open positions every 2 seconds. Checks exit conditions: SL hit, target hit, EOD square-off (15:15 IST for scalp/intraday). Triggers EXIT_ORDER events on the `trade_executions` channel.

### FastAPI Server
- Runs on port 8000 alongside the agent pipeline
- REST endpoints at `/api/`: dashboard, trades, trade detail, signals, agents, news, settings, audit, healthz
- WebSocket at `/ws`: streams ticks, trade executions, agent status, signals, news in real-time
- Settings endpoint supports paper/live mode toggle with PIN verification for live mode

### Configuration (config.py)
All config loaded from environment variables:
- TrueData credentials: `TRUEDATA_USERNAME`, `TRUEDATA_PASSWORD`
- Zerodha: `ZERODHA_API_KEY`, `ZERODHA_API_SECRET`, `ZERODHA_ACCESS_TOKEN`
- Anthropic: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- Database: `DATABASE_URL`
- Redis: `REDIS_URL`
- Trading: `TRADING_MODE` (paper/live), `TRADING_CAPITAL`, `CONSENSUS_THRESHOLD`
- Risk: `MAX_DAILY_LOSS`, `MAX_TRADE_RISK_PCT`, `MAX_OPEN_POSITIONS`, `VIX_HALT_THRESHOLD`

## TypeScript & Composite Projects

Every package extends `tsconfig.base.json` which sets `composite: true`. The root `tsconfig.json` lists all packages as project references. This means:

- **Always typecheck from the root** — run `pnpm run typecheck` (which runs `tsc --build --emitDeclarationOnly`). This builds the full dependency graph so that cross-package imports resolve correctly. Running `tsc` inside a single package will fail if its dependencies haven't been built yet.
- **`emitDeclarationOnly`** — we only emit `.d.ts` files during typecheck; actual JS bundling is handled by esbuild/tsx/vite...etc, not `tsc`.
- **Project references** — when package A depends on package B, A's `tsconfig.json` must list B in its `references` array. `tsc --build` uses this to determine build order and skip up-to-date packages.

## Root Scripts

- `pnpm run build` — runs `typecheck` first, then recursively runs `build` in all packages that define it
- `pnpm run typecheck` — runs `tsc --build --emitDeclarationOnly` using project references

## Packages

### `artifacts/api-server` (`@workspace/api-server`)

Express 5 API server. Routes live in `src/routes/` and use `@workspace/api-zod` for request and response validation and `@workspace/db` for persistence.

- Entry: `src/index.ts` — reads `PORT`, starts Express
- App setup: `src/app.ts` — mounts CORS, JSON/urlencoded parsing, routes at `/api`
- Routes: `src/routes/index.ts` mounts sub-routers; `src/routes/health.ts` exposes `GET /health` (full path: `/api/health`)
- Depends on: `@workspace/db`, `@workspace/api-zod`
- `pnpm --filter @workspace/api-server run dev` — run the dev server
- `pnpm --filter @workspace/api-server run build` — production esbuild bundle (`dist/index.cjs`)
- Build bundles an allowlist of deps (express, cors, pg, drizzle-orm, zod, etc.) and externalizes the rest

### `lib/db` (`@workspace/db`)

Database layer using Drizzle ORM with PostgreSQL. Exports a Drizzle client instance and schema models.

- `src/index.ts` — creates a `Pool` + Drizzle instance, exports schema
- `src/schema/index.ts` — barrel re-export of all models
- `src/schema/signals.ts` — signals table (agent analysis outputs)
- `src/schema/trades.ts` — trades table (full trade lifecycle)
- `src/schema/agent_votes.ts` — agent vote records per trade
- `src/schema/audit_logs.ts` — system event audit trail
- `drizzle.config.ts` — Drizzle Kit config (requires `DATABASE_URL`, automatically provided by Replit)
- Exports: `.` (pool, db, schema), `./schema` (schema only)

Production migrations are handled by Replit when publishing. In development, we just use `pnpm --filter @workspace/db run push`, and we fallback to `pnpm --filter @workspace/db run push-force`.

### `lib/api-spec` (`@workspace/api-spec`)

Owns the OpenAPI 3.1 spec (`openapi.yaml`) and the Orval config (`orval.config.ts`). Running codegen produces output into two sibling packages:

1. `lib/api-client-react/src/generated/` — React Query hooks + fetch client
2. `lib/api-zod/src/generated/` — Zod schemas

Run codegen: `pnpm --filter @workspace/api-spec run codegen`

### `lib/api-zod` (`@workspace/api-zod`)

Generated Zod schemas from the OpenAPI spec (e.g. `HealthCheckResponse`). Used by `api-server` for response validation.

### `lib/api-client-react` (`@workspace/api-client-react`)

Generated React Query hooks and fetch client from the OpenAPI spec (e.g. `useHealthCheck`, `healthCheck`).

### `scripts` (`@workspace/scripts`)

Utility scripts package. Each script is a `.ts` file in `src/` with a corresponding npm script in `package.json`. Run scripts via `pnpm --filter @workspace/scripts run <script>`. Scripts can import any workspace package (e.g., `@workspace/db`) by adding it as a dependency in `scripts/package.json`.
