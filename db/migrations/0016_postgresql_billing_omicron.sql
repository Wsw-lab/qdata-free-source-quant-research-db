-- A 股量化数据平台 Omicron：月度账单、账单明细和收入回款状态

CREATE TABLE IF NOT EXISTS qmeta.invoice (
    invoice_id          BIGSERIAL PRIMARY KEY,
    invoice_code        VARCHAR(180) NOT NULL UNIQUE,
    tenant_id           BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id),
    project_id          BIGINT REFERENCES qmeta.project(project_id),
    subscription_id     BIGINT REFERENCES qmeta.product_subscription(subscription_id),
    plan_id             BIGINT REFERENCES qmeta.pricing_plan(plan_id),
    product_id          BIGINT REFERENCES qmeta.data_product(product_id),
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    invoice_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    due_date            DATE,
    currency            VARCHAR(16) NOT NULL DEFAULT 'CNY',
    status              VARCHAR(24) NOT NULL DEFAULT 'draft',
    subtotal_amount     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    discount_amount     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    tax_amount          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    total_amount        NUMERIC(24, 8) NOT NULL DEFAULT 0,
    paid_amount         NUMERIC(24, 8) NOT NULL DEFAULT 0,
    outstanding_amount  NUMERIC(24, 8) NOT NULL DEFAULT 0,
    issued_at           TIMESTAMPTZ,
    paid_at             TIMESTAMPTZ,
    voided_at           TIMESTAMPTZ,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start),
    CHECK (due_date IS NULL OR due_date >= invoice_date),
    CHECK (status IN ('draft', 'issued', 'partially_paid', 'paid', 'overdue', 'void')),
    CHECK (subtotal_amount >= 0),
    CHECK (discount_amount >= 0),
    CHECK (tax_amount >= 0),
    CHECK (total_amount >= 0),
    CHECK (paid_amount >= 0),
    CHECK (outstanding_amount >= 0),
    CHECK (paid_amount <= total_amount)
);

CREATE INDEX IF NOT EXISTS idx_invoice_tenant_period
    ON qmeta.invoice(tenant_id, project_id, period_start DESC, period_end DESC);

CREATE INDEX IF NOT EXISTS idx_invoice_status_due
    ON qmeta.invoice(status, due_date, invoice_date DESC);

CREATE INDEX IF NOT EXISTS idx_invoice_subscription_period
    ON qmeta.invoice(subscription_id, period_start DESC, period_end DESC);

CREATE TABLE IF NOT EXISTS qmeta.invoice_line (
    line_id             BIGSERIAL PRIMARY KEY,
    invoice_id          BIGINT NOT NULL REFERENCES qmeta.invoice(invoice_id) ON DELETE CASCADE,
    line_code           VARCHAR(220) NOT NULL UNIQUE,
    product_id          BIGINT REFERENCES qmeta.data_product(product_id),
    pricing_rule_id     BIGINT REFERENCES qmeta.pricing_rule(rule_id) ON DELETE SET NULL,
    api_name            VARCHAR(128),
    metric_name         VARCHAR(32) NOT NULL,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    quantity            NUMERIC(24, 8) NOT NULL DEFAULT 0,
    unit_price          NUMERIC(24, 10) NOT NULL DEFAULT 0,
    amount              NUMERIC(24, 8) NOT NULL DEFAULT 0,
    request_count       BIGINT NOT NULL DEFAULT 0,
    row_count           BIGINT NOT NULL DEFAULT 0,
    cost_units          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start),
    CHECK (metric_name IN ('request', 'row', 'cost_unit', 'export', 'monthly_fee', 'base_fee', 'adjustment')),
    CHECK (quantity >= 0),
    CHECK (unit_price >= 0),
    CHECK (amount >= 0),
    CHECK (request_count >= 0),
    CHECK (row_count >= 0),
    CHECK (cost_units >= 0)
);

CREATE INDEX IF NOT EXISTS idx_invoice_line_invoice
    ON qmeta.invoice_line(invoice_id, line_id);

CREATE INDEX IF NOT EXISTS idx_invoice_line_product_api
    ON qmeta.invoice_line(product_id, api_name, metric_name);

CREATE TABLE IF NOT EXISTS qmeta.invoice_event (
    event_id            BIGSERIAL PRIMARY KEY,
    invoice_id          BIGINT NOT NULL REFERENCES qmeta.invoice(invoice_id) ON DELETE CASCADE,
    event_code          VARCHAR(220) NOT NULL UNIQUE,
    event_type          VARCHAR(64) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'success',
    message             TEXT,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (event_type IN ('generated', 'issued', 'paid', 'overdue', 'void', 'manual_note')),
    CHECK (status IN ('success', 'warning', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_invoice_event_invoice_time
    ON qmeta.invoice_event(invoice_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_invoice_event_type_time
    ON qmeta.invoice_event(event_type, created_at DESC);
