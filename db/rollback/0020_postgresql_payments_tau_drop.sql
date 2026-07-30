-- Rollback Tau payment and revenue ledger metadata.

DROP TABLE IF EXISTS qmeta.revenue_ledger_entry CASCADE;
DROP TABLE IF EXISTS qmeta.payment_invoice_match CASCADE;
DROP TABLE IF EXISTS qmeta.payment_transaction CASCADE;
DROP TABLE IF EXISTS qmeta.payment_import_batch CASCADE;
DROP TABLE IF EXISTS qmeta.fx_rate_daily CASCADE;
