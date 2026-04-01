CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

SELECT create_hypertable('signals', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);

SELECT create_hypertable('trade_log', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);

SELECT create_hypertable('audit_logs', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);

CREATE INDEX IF NOT EXISTS idx_signals_agent_id ON signals (agent_id, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_signals_underlying ON signals (underlying, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_trade_log_trade_id ON trade_log (trade_id, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_event_type ON audit_logs (event_type, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);
CREATE INDEX IF NOT EXISTS idx_trades_underlying ON trades (underlying, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_votes_trade_id ON agent_votes (trade_id);
