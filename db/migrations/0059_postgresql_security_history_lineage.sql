-- Historical security identities are PIT inputs, not current-master labels.
--
-- Legacy rows intentionally remain NULL after this forward-only migration:
-- without a provable batch and knowledge timestamp they must not be admitted by
-- PIT selectors. Re-ingestion or the deterministic seed can backfill lineage.

ALTER TABLE qmeta.security_identifier_history
    ADD COLUMN IF NOT EXISTS announce_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ingest_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS batch_id BIGINT REFERENCES qmeta.data_batch(batch_id);

ALTER TABLE qmeta.security_name_history
    ADD COLUMN IF NOT EXISTS announce_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ingest_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS batch_id BIGINT REFERENCES qmeta.data_batch(batch_id);

ALTER TABLE qmeta.security_status_history
    ADD COLUMN IF NOT EXISTS announce_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ingest_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS batch_id BIGINT REFERENCES qmeta.data_batch(batch_id);

CREATE INDEX IF NOT EXISTS idx_security_identifier_knowledge
    ON qmeta.security_identifier_history(security_id, start_date, ingest_time, batch_id);

CREATE INDEX IF NOT EXISTS idx_security_name_knowledge
    ON qmeta.security_name_history(security_id, start_date, ingest_time, batch_id);

CREATE INDEX IF NOT EXISTS idx_security_status_knowledge
    ON qmeta.security_status_history(security_id, start_date, ingest_time, batch_id);

-- The loader writes these richer trading states into both the current master
-- and its append-only status history. Legacy fresh schemas only admitted the
-- coarser active/suspended/delisted set.
ALTER TABLE qmeta.security_master
    DROP CONSTRAINT IF EXISTS security_master_current_status_check;

ALTER TABLE qmeta.security_master
    DROP CONSTRAINT IF EXISTS ck_security_master_current_status;

ALTER TABLE qmeta.security_master
    ADD CONSTRAINT ck_security_master_current_status CHECK (
        current_status IN (
            'prelisted', 'active', 'suspended', 'st', 'star_st',
            'delisting_period', 'delisted', 'terminated', 'unknown'
        )
    );
