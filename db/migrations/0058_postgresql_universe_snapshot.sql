-- Bind every rule-based universe snapshot, including an empty snapshot, to its
-- ingestion batch.  The batch lifecycle supplies the knowledge-time boundary.

CREATE TABLE IF NOT EXISTS qmeta.universe_snapshot (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    universe_id         BIGINT NOT NULL REFERENCES qmeta.universe_definition(universe_id),
    trade_date          DATE NOT NULL,
    batch_id            BIGINT NOT NULL REFERENCES qmeta.data_batch(batch_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (universe_id, trade_date, batch_id)
);

CREATE INDEX IF NOT EXISTS idx_universe_snapshot_selection
    ON qmeta.universe_snapshot(universe_id, trade_date, batch_id DESC);
