-- A 股全市场日频生产 Gamma：增量、回补、质量闭环

ALTER TABLE qmeta.pipeline_run
    ADD COLUMN IF NOT EXISTS expected_by_exchange JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS actual_by_exchange JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS missing_by_exchange JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS missing_explanations JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS repair_status VARCHAR(24) NOT NULL DEFAULT 'none';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_pipeline_run_repair_status'
          AND conrelid = 'qmeta.pipeline_run'::regclass
    ) THEN
        ALTER TABLE qmeta.pipeline_run
            ADD CONSTRAINT chk_pipeline_run_repair_status
            CHECK (repair_status IN ('none', 'queued', 'resolved', 'ignored'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS qmeta.pipeline_repair_queue (
    repair_id           BIGSERIAL PRIMARY KEY,
    job_id              BIGINT NOT NULL REFERENCES qmeta.pipeline_job(job_id),
    run_id              BIGINT REFERENCES qmeta.pipeline_run(run_id),
    trade_date          DATE NOT NULL,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    reason              VARCHAR(64) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'open',
    expected_row_count  BIGINT,
    row_count           BIGINT,
    missing_count       BIGINT NOT NULL DEFAULT 0,
    missing_symbols     TEXT[] NOT NULL DEFAULT '{}',
    completeness_rate   NUMERIC(12, 8),
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ,
    UNIQUE (job_id, trade_date, reason),
    CHECK (status IN ('open', 'in_progress', 'resolved', 'ignored')),
    CHECK (reason IN ('failed', 'partial_success', 'completeness_below_threshold')),
    CHECK (expected_row_count IS NULL OR expected_row_count >= 0),
    CHECK (row_count IS NULL OR row_count >= 0),
    CHECK (missing_count >= 0),
    CHECK (completeness_rate IS NULL OR (completeness_rate >= 0 AND completeness_rate <= 1))
);

CREATE INDEX IF NOT EXISTS idx_pipeline_repair_status_date
    ON qmeta.pipeline_repair_queue(status, trade_date, updated_at);

CREATE INDEX IF NOT EXISTS idx_pipeline_repair_job_date
    ON qmeta.pipeline_repair_queue(job_id, trade_date DESC, status);
