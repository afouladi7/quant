-- MarketLab persistent-mode schema v1.
-- Live simulation state stays in memory (authoritative, single process); these
-- tables archive history so it survives restarts.

CREATE TABLE IF NOT EXISTS app_instances (
    instance_id   UUID PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL,
    version       TEXT NOT NULL,
    environment   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    instance_id     UUID NOT NULL,
    seq             BIGINT NOT NULL,
    event_id        TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    mono_ns         BIGINT NOT NULL,
    type            TEXT NOT NULL,
    module          TEXT NOT NULL,
    entity_id       TEXT,
    correlation_id  TEXT,
    message         TEXT NOT NULL,
    data            JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (instance_id, seq)
);
CREATE INDEX IF NOT EXISTS events_ts_idx ON events (ts DESC);
CREATE INDEX IF NOT EXISTS events_corr_idx ON events (correlation_id);
CREATE INDEX IF NOT EXISTS events_type_idx ON events (type);

CREATE TABLE IF NOT EXISTS trades (
    instance_id     UUID NOT NULL,
    trade_id        TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    module          TEXT NOT NULL,
    venue           TEXT NOT NULL,
    price           NUMERIC(24, 10) NOT NULL,
    quantity        BIGINT NOT NULL,
    taker_order_id  TEXT NOT NULL,
    maker_order_id  TEXT NOT NULL,
    taker_owner     TEXT NOT NULL,
    maker_owner     TEXT NOT NULL,
    taker_fee       NUMERIC(24, 10) NOT NULL,
    maker_fee       NUMERIC(24, 10) NOT NULL,
    correlation_id  TEXT,
    PRIMARY KEY (instance_id, trade_id)
);
CREATE INDEX IF NOT EXISTS trades_ts_idx ON trades (ts DESC);

CREATE TABLE IF NOT EXISTS benchmark_runs (
    instance_id   UUID NOT NULL,
    run_id        TEXT NOT NULL,
    suite_id      TEXT,
    status        TEXT NOT NULL,
    description   TEXT NOT NULL,
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    config        JSONB NOT NULL,
    summary       JSONB NOT NULL,
    phase_medians JSONB NOT NULL,
    environment   JSONB NOT NULL,
    notes         JSONB NOT NULL,
    trials        JSONB NOT NULL,
    PRIMARY KEY (instance_id, run_id)
);

CREATE TABLE IF NOT EXISTS configs (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
