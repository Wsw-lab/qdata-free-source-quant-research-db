-- Rollback Phi strategy engine metadata.

DROP TABLE IF EXISTS qmeta.strategy_escalation_event CASCADE;
DROP TABLE IF EXISTS qmeta.strategy_decision CASCADE;
DROP TABLE IF EXISTS qmeta.strategy_signal CASCADE;
DROP TABLE IF EXISTS qmeta.strategy_run CASCADE;
DROP TABLE IF EXISTS qmeta.strategy_policy CASCADE;
