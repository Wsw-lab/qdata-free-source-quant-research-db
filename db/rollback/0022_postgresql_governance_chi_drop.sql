-- Roll back Chi governance metadata.

DROP TABLE IF EXISTS qmeta.governance_action CASCADE;
DROP TABLE IF EXISTS qmeta.project_governance_snapshot CASCADE;
DROP TABLE IF EXISTS qmeta.access_decision_audit CASCADE;
