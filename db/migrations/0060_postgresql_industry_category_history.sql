-- Industry display labels and levels are historical research inputs.
-- Legacy current-category rows are not copied automatically because they lack
-- provable announce/ingest/batch lineage; re-ingestion or the deterministic
-- seed must backfill them before PIT queries can expose a label.

CREATE TABLE IF NOT EXISTS qmeta.industry_category_history (
    industry_id         BIGINT NOT NULL REFERENCES qmeta.industry_category(industry_id),
    industry_system_id  BIGINT NOT NULL REFERENCES qmeta.industry_system(industry_system_id),
    industry_code       VARCHAR(64) NOT NULL,
    industry_name       VARCHAR(128) NOT NULL,
    level               SMALLINT NOT NULL,
    parent_industry_id  BIGINT REFERENCES qmeta.industry_category(industry_id),
    start_date          DATE NOT NULL,
    end_date            DATE,
    announce_time       TIMESTAMPTZ NOT NULL,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT NOT NULL REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (industry_id, start_date, revision_id),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_industry_category_history_asof
    ON qmeta.industry_category_history(
        industry_system_id, level, start_date, ingest_time, batch_id
    );
