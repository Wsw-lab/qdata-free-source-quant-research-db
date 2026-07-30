-- Roll back Omicron invoice, invoice line and invoice event metadata.

DROP TABLE IF EXISTS qmeta.invoice_event CASCADE;
DROP TABLE IF EXISTS qmeta.invoice_line CASCADE;
DROP TABLE IF EXISTS qmeta.invoice CASCADE;
