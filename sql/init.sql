-- sql/init.sql
-- =============
-- Lahraoui-NeuralForex-Pro – PostgreSQL schema initialisation
-- Runs automatically when the postgres container is first created.

-- ── Trades table (order execution log) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades (
    id              SERIAL PRIMARY KEY,
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    symbol          VARCHAR(10)  NOT NULL DEFAULT 'EURUSD',
    direction       VARCHAR(4)   NOT NULL CHECK (direction IN ('BUY', 'SELL')),
    lot_size        NUMERIC(8,2) NOT NULL,
    entry_price     NUMERIC(10,5) NOT NULL,
    stop_loss       NUMERIC(10,5),
    take_profit     NUMERIC(10,5),
    close_price     NUMERIC(10,5),
    pnl_pips        NUMERIC(10,2),
    pnl_usd         NUMERIC(12,2),
    status          VARCHAR(10) NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN', 'CLOSED', 'CANCELLED')),
    model_signal    VARCHAR(4),
    model_confidence NUMERIC(5,4),
    notes           TEXT
);

-- ── AI predictions log ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS predictions (
    id              SERIAL PRIMARY KEY,
    predicted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol          VARCHAR(10) NOT NULL DEFAULT 'EURUSD',
    signal          VARCHAR(4)  NOT NULL,
    confidence      NUMERIC(5,4),
    prob_buy        NUMERIC(5,4),
    prob_hold       NUMERIC(5,4),
    prob_sell       NUMERIC(5,4),
    model_version   VARCHAR(50)
);

-- ── Sentiment log ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentiment_log (
    id              SERIAL PRIMARY KEY,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    institution     VARCHAR(10) NOT NULL,  -- 'FED' or 'ECB'
    score           NUMERIC(6,4),
    bias            VARCHAR(10),
    headlines_count INTEGER
);

-- ── Heartbeat log ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS heartbeat_log (
    id              SERIAL PRIMARY KEY,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    service         VARCHAR(50) NOT NULL,
    healthy         BOOLEAN NOT NULL,
    response_ms     INTEGER,
    error_message   TEXT
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_trades_opened_at   ON trades (opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status      ON trades (status);
CREATE INDEX IF NOT EXISTS idx_predictions_ts     ON predictions (predicted_at DESC);
CREATE INDEX IF NOT EXISTS idx_sentiment_inst_ts  ON sentiment_log (institution, recorded_at DESC);
