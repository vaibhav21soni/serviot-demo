-- 001_init.sql
-- Idempotent schema. Safe to re-run on every startup and as a pipeline step.

CREATE TABLE IF NOT EXISTS devices (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(120) NOT NULL,
    type        VARCHAR(60)  NOT NULL,
    status      VARCHAR(20)  NOT NULL DEFAULT 'offline'
                CHECK (status IN ('online', 'offline', 'maintenance')),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_devices_status ON devices (status);
