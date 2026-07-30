-- Roll back Zeta ops dashboard/SLA metadata only.

DROP TABLE IF EXISTS qmeta.ops_dashboard_snapshot CASCADE;
DROP TABLE IF EXISTS qmeta.alert_event CASCADE;
DROP TABLE IF EXISTS qmeta.sla_policy CASCADE;
