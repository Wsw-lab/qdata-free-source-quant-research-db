-- Make market-data vintages durable across ReplacingMergeTree background merges.
--
-- This is a one-time migration for existing ClickHouse tables.  ClickHouse only
-- permits MODIFY ORDER BY to reference existing sorting-key columns plus columns
-- added by the same ALTER, so version_key is introduced as a materialized alias.
-- Existing parts remain in place; future merges compute version_key from the
-- retained data_version and replace retries only within the same data version.
--
-- IMPORTANT: rows already removed by merges under the old sorting key cannot be
-- reconstructed by this migration and must be restored from source snapshots.

ALTER TABLE qts.daily_bar
    ADD COLUMN version_key UInt64 MATERIALIZED data_version AFTER data_version,
    MODIFY ORDER BY (security_id, trade_date, version_key);

ALTER TABLE qts.minute_bar
    ADD COLUMN version_key UInt64 MATERIALIZED data_version AFTER data_version,
    MODIFY ORDER BY (security_id, trade_date, bar_time, version_key);
