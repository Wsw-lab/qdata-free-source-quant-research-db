-- A 股量化行情 Delta：复权、交易约束、可交易股票池和矩阵出口

CREATE INDEX IF NOT EXISTS idx_adjustment_factor_security_date_revision
    ON qmeta.adjustment_factor(security_id, trade_date DESC, revision_id DESC);

CREATE INDEX IF NOT EXISTS idx_limit_price_security_date_revision
    ON qmeta.limit_price_daily(security_id, trade_date DESC, revision_id DESC);

CREATE INDEX IF NOT EXISTS idx_universe_member_pit_universe_asof
    ON qpit.universe_member_pit(universe_id, effective_date DESC, end_date, security_id);

CREATE TABLE IF NOT EXISTS qmeta.matrix_export_audit (
    export_id           BIGSERIAL PRIMARY KEY,
    export_code         VARCHAR(128),
    dataset_code        VARCHAR(96) NOT NULL,
    field_name          VARCHAR(128) NOT NULL,
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    symbol_count        BIGINT NOT NULL DEFAULT 0,
    row_count           BIGINT NOT NULL DEFAULT 0,
    output_uri          TEXT NOT NULL,
    output_format       VARCHAR(24) NOT NULL,
    request_summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date),
    CHECK (symbol_count >= 0),
    CHECK (row_count >= 0),
    CHECK (output_format IN ('csv', 'parquet'))
);

CREATE INDEX IF NOT EXISTS idx_matrix_export_audit_dataset_date
    ON qmeta.matrix_export_audit(dataset_code, end_date DESC, created_at DESC);
