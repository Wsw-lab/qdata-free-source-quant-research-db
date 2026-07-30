-- A 股量化数据平台 Tau：真实回款流水、自动匹配和收入 ledger

CREATE TABLE IF NOT EXISTS qmeta.fx_rate_daily (
    rate_id                 BIGSERIAL PRIMARY KEY,
    rate_code               VARCHAR(180) NOT NULL UNIQUE,
    rate_date               DATE NOT NULL,
    from_currency           VARCHAR(16) NOT NULL,
    to_currency             VARCHAR(16) NOT NULL DEFAULT 'CNY',
    rate                    NUMERIC(24, 12) NOT NULL,
    provider                VARCHAR(64) NOT NULL DEFAULT 'manual',
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (rate_date, from_currency, to_currency, provider),
    CHECK (from_currency <> ''),
    CHECK (to_currency <> ''),
    CHECK (rate > 0)
);

CREATE INDEX IF NOT EXISTS idx_fx_rate_daily_lookup
    ON qmeta.fx_rate_daily(rate_date DESC, from_currency, to_currency);

CREATE TABLE IF NOT EXISTS qmeta.payment_import_batch (
    batch_id                BIGSERIAL PRIMARY KEY,
    batch_code              VARCHAR(180) NOT NULL UNIQUE,
    source_type             VARCHAR(32) NOT NULL,
    account_code            VARCHAR(128),
    statement_start         DATE,
    statement_end           DATE,
    currency                VARCHAR(16) NOT NULL DEFAULT 'CNY',
    status                  VARCHAR(24) NOT NULL DEFAULT 'imported',
    transaction_count       INTEGER NOT NULL DEFAULT 0,
    matched_count           INTEGER NOT NULL DEFAULT 0,
    unmatched_count         INTEGER NOT NULL DEFAULT 0,
    total_amount            NUMERIC(24, 8) NOT NULL DEFAULT 0,
    matched_amount          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    unmatched_amount        NUMERIC(24, 8) NOT NULL DEFAULT 0,
    imported_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (source_type IN ('bank_csv', 'alipay_csv', 'wechat_csv', 'manual_csv', 'api', 'demo')),
    CHECK (status IN ('imported', 'matched', 'partially_matched', 'failed', 'void')),
    CHECK (statement_end IS NULL OR statement_start IS NULL OR statement_end >= statement_start),
    CHECK (transaction_count >= 0),
    CHECK (matched_count >= 0),
    CHECK (unmatched_count >= 0),
    CHECK (total_amount >= 0),
    CHECK (matched_amount >= 0),
    CHECK (unmatched_amount >= 0)
);

CREATE INDEX IF NOT EXISTS idx_payment_import_batch_status
    ON qmeta.payment_import_batch(status, imported_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.payment_transaction (
    transaction_id          BIGSERIAL PRIMARY KEY,
    transaction_code        VARCHAR(220) NOT NULL UNIQUE,
    batch_id                BIGINT REFERENCES qmeta.payment_import_batch(batch_id) ON DELETE SET NULL,
    tenant_id               BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id              BIGINT REFERENCES qmeta.project(project_id),
    invoice_id              BIGINT REFERENCES qmeta.invoice(invoice_id) ON DELETE SET NULL,
    payment_channel         VARCHAR(32) NOT NULL DEFAULT 'bank',
    external_transaction_id VARCHAR(160),
    counterparty_name       VARCHAR(180),
    counterparty_account    VARCHAR(180),
    transaction_time        TIMESTAMPTZ NOT NULL,
    value_date              DATE NOT NULL,
    direction               VARCHAR(16) NOT NULL DEFAULT 'inbound',
    currency                VARCHAR(16) NOT NULL DEFAULT 'CNY',
    amount                  NUMERIC(24, 8) NOT NULL,
    base_currency           VARCHAR(16) NOT NULL DEFAULT 'CNY',
    fx_rate_to_base         NUMERIC(24, 12) NOT NULL DEFAULT 1,
    base_amount             NUMERIC(24, 8) NOT NULL,
    status                  VARCHAR(24) NOT NULL DEFAULT 'imported',
    reference_text          TEXT,
    raw_payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (payment_channel IN ('bank', 'alipay', 'wechat', 'manual', 'api')),
    CHECK (direction IN ('inbound', 'outbound')),
    CHECK (status IN ('imported', 'matched', 'partially_matched', 'overpaid', 'unmatched', 'ignored', 'reversed')),
    CHECK (amount >= 0),
    CHECK (fx_rate_to_base > 0),
    CHECK (base_amount >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_transaction_external
    ON qmeta.payment_transaction(batch_id, external_transaction_id)
    WHERE external_transaction_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_payment_transaction_status
    ON qmeta.payment_transaction(status, value_date DESC, amount DESC);

CREATE INDEX IF NOT EXISTS idx_payment_transaction_invoice
    ON qmeta.payment_transaction(invoice_id, value_date DESC);

CREATE TABLE IF NOT EXISTS qmeta.payment_invoice_match (
    match_id                BIGSERIAL PRIMARY KEY,
    match_code              VARCHAR(240) NOT NULL UNIQUE,
    transaction_id          BIGINT NOT NULL REFERENCES qmeta.payment_transaction(transaction_id) ON DELETE CASCADE,
    invoice_id              BIGINT NOT NULL REFERENCES qmeta.invoice(invoice_id) ON DELETE CASCADE,
    tenant_id               BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id              BIGINT REFERENCES qmeta.project(project_id),
    match_type              VARCHAR(32) NOT NULL,
    status                  VARCHAR(24) NOT NULL,
    currency                VARCHAR(16) NOT NULL DEFAULT 'CNY',
    matched_amount          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    base_currency           VARCHAR(16) NOT NULL DEFAULT 'CNY',
    fx_rate_to_base         NUMERIC(24, 12) NOT NULL DEFAULT 1,
    base_matched_amount     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    unmatched_amount        NUMERIC(24, 8) NOT NULL DEFAULT 0,
    match_score             NUMERIC(8, 6) NOT NULL DEFAULT 1,
    matched_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (transaction_id, invoice_id),
    CHECK (match_type IN ('auto_exact', 'auto_partial', 'auto_overpay', 'manual', 'rule_suggested')),
    CHECK (status IN ('matched', 'partial', 'overpaid', 'unmatched', 'reversed')),
    CHECK (matched_amount >= 0),
    CHECK (fx_rate_to_base > 0),
    CHECK (base_matched_amount >= 0),
    CHECK (unmatched_amount >= 0),
    CHECK (match_score >= 0 AND match_score <= 1)
);

CREATE INDEX IF NOT EXISTS idx_payment_invoice_match_status
    ON qmeta.payment_invoice_match(status, matched_at DESC);

CREATE INDEX IF NOT EXISTS idx_payment_invoice_match_invoice
    ON qmeta.payment_invoice_match(invoice_id, status, matched_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.revenue_ledger_entry (
    ledger_id               BIGSERIAL PRIMARY KEY,
    ledger_code             VARCHAR(240) NOT NULL UNIQUE,
    tenant_id               BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id              BIGINT REFERENCES qmeta.project(project_id),
    invoice_id              BIGINT REFERENCES qmeta.invoice(invoice_id) ON DELETE SET NULL,
    transaction_id          BIGINT REFERENCES qmeta.payment_transaction(transaction_id) ON DELETE SET NULL,
    match_id                BIGINT REFERENCES qmeta.payment_invoice_match(match_id) ON DELETE SET NULL,
    entry_date              DATE NOT NULL,
    entry_type              VARCHAR(32) NOT NULL,
    currency                VARCHAR(16) NOT NULL DEFAULT 'CNY',
    debit_amount            NUMERIC(24, 8) NOT NULL DEFAULT 0,
    credit_amount           NUMERIC(24, 8) NOT NULL DEFAULT 0,
    balance_amount          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    base_currency           VARCHAR(16) NOT NULL DEFAULT 'CNY',
    base_debit_amount       NUMERIC(24, 8) NOT NULL DEFAULT 0,
    base_credit_amount      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    base_balance_amount     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (entry_type IN ('invoice_issued', 'payment_received', 'payment_matched', 'payment_unmatched', 'refund', 'adjustment')),
    CHECK (debit_amount >= 0),
    CHECK (credit_amount >= 0),
    CHECK (balance_amount >= 0),
    CHECK (base_debit_amount >= 0),
    CHECK (base_credit_amount >= 0),
    CHECK (base_balance_amount >= 0)
);

CREATE INDEX IF NOT EXISTS idx_revenue_ledger_entry_date
    ON qmeta.revenue_ledger_entry(entry_date DESC, entry_type);

CREATE INDEX IF NOT EXISTS idx_revenue_ledger_entry_invoice
    ON qmeta.revenue_ledger_entry(invoice_id, entry_date DESC);
