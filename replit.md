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
│   ├── data_pipeline/      # TrueData feeds + Redis publisher
│   │   ├── truedata_feed.py
│   │   ├── options_chain_feed.py
│   │   └── redis_publisher.py
│   ├── agents/             # 12 AI agents
│   │   ├── base_agent.py   # Shared lifecycle: market-hours, Redis, signals
│   │   ├── llm_utils.py    # Claude API helper (query_claude)
│   │   ├── options_chain_agent.py  # Agent 1: Options chain analysis
│   │   ├── order_flow_agent.py     # Agent 2: Order flow (rule-based)
│   │   ├── volume_profile_agent.py # Agent 3: Volume profile (rule-based)
│   │   ├── technical_agent.py      # Agent 4: Multi-TF technical (rule-based)
│   │   ├── sentiment_agent.py      # Agent 5: Market sentiment (LLM)
│   │   ├── news_agent.py           # Agent 6: News & events (LLM)
│   │   └── macro_agent.py          # Agent 7: Global macro (LLM)
│   ├── execution/          # Paper + live trade executors
│   └── api/                # FastAPI routes + WebSocket
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

### Redis Channels
- `niftymind:ticks` — Raw tick-by-tick data
- `niftymind:options_chain` — Options chain snapshots
- `niftymind:ohlc:{1m,5m,15m}` — OHLC candles
- `niftymind:signals` — Agent signals
- `niftymind:trade_proposals` — Trade proposals from decision agents
- `niftymind:trade_executions` — Executed trade confirmations
- `niftymind:agent_status` — Agent health/state updates

### Agent Architecture
- **BaseAgent** (`base_agent.py`): Shared lifecycle with market-hours gate (9:15–15:30 IST), expiry-day detection (Thursday), Redis pub/sub subscription, Signal emission, and graceful shutdown
- **Signal dataclass**: agent_id, timestamp, underlying, direction (BULLISH/BEARISH/NEUTRAL), confidence (0–1), timeframe (SCALP/INTRADAY/BTST), reasoning, supporting_data
- **LLM agents** (1, 5, 6, 7): Use Claude API via `llm_utils.query_claude()` for reasoning
- **Rule-based agents** (2, 3, 4): Pure computation, no LLM calls — optimized for low latency
- Agents 5 (Sentiment), 6 (News), 7 (Macro) also run outside market hours (pre-market/always-on)

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
