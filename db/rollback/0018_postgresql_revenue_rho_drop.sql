-- Rollback Rho revenue reconciliation metadata.

DROP TABLE IF EXISTS qmeta.customer_health_snapshot CASCADE;
DROP TABLE IF EXISTS qmeta.ar_aging_snapshot CASCADE;
DROP TABLE IF EXISTS qmeta.revenue_reconciliation_line CASCADE;
DROP TABLE IF EXISTS qmeta.revenue_reconciliation_run CASCADE;
