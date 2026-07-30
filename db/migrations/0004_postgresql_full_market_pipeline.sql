-- Full-market daily production Beta metadata.

ALTER TABLE qmeta.pipeline_job
    ADD COLUMN IF NOT EXISTS all_market BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS batch_size INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_symbols INTEGER,
    ADD COLUMN IF NOT EXISTS min_completeness NUMERIC(12, 8) NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS skip_closed_days BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS sleep_seconds NUMERIC(12, 3) NOT NULL DEFAULT 0;

ALTER TABLE qmeta.pipeline_job
    DROP CONSTRAINT IF EXISTS chk_pipeline_job_batch_size,
    ADD CONSTRAINT chk_pipeline_job_batch_size CHECK (batch_size >= 0);

ALTER TABLE qmeta.pipeline_job
    DROP CONSTRAINT IF EXISTS chk_pipeline_job_max_symbols,
    ADD CONSTRAINT chk_pipeline_job_max_symbols CHECK (max_symbols IS NULL OR max_symbols > 0);

ALTER TABLE qmeta.pipeline_job
    DROP CONSTRAINT IF EXISTS chk_pipeline_job_min_completeness,
    ADD CONSTRAINT chk_pipeline_job_min_completeness CHECK (min_completeness >= 0 AND min_completeness <= 1);

ALTER TABLE qmeta.pipeline_job
    DROP CONSTRAINT IF EXISTS chk_pipeline_job_sleep_seconds,
    ADD CONSTRAINT chk_pipeline_job_sleep_seconds CHECK (sleep_seconds >= 0);

ALTER TABLE qmeta.pipeline_run
    ADD COLUMN IF NOT EXISTS expected_row_count BIGINT,
    ADD COLUMN IF NOT EXISTS missing_count BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS missing_symbols TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS completeness_rate NUMERIC(12, 8),
    ADD COLUMN IF NOT EXISTS batch_count INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS all_market BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE qmeta.pipeline_run
    DROP CONSTRAINT IF EXISTS chk_pipeline_run_expected_row_count,
    ADD CONSTRAINT chk_pipeline_run_expected_row_count CHECK (expected_row_count IS NULL OR expected_row_count >= 0);

ALTER TABLE qmeta.pipeline_run
    DROP CONSTRAINT IF EXISTS chk_pipeline_run_missing_count,
    ADD CONSTRAINT chk_pipeline_run_missing_count CHECK (missing_count >= 0);

ALTER TABLE qmeta.pipeline_run
    DROP CONSTRAINT IF EXISTS chk_pipeline_run_completeness_rate,
    ADD CONSTRAINT chk_pipeline_run_completeness_rate CHECK (completeness_rate IS NULL OR (completeness_rate >= 0 AND completeness_rate <= 1));

ALTER TABLE qmeta.pipeline_run
    DROP CONSTRAINT IF EXISTS chk_pipeline_run_batch_count,
    ADD CONSTRAINT chk_pipeline_run_batch_count CHECK (batch_count >= 0);
