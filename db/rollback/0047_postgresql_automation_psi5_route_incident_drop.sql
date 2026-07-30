-- Rollback Psi-5 source-route incident automation.

DELETE FROM qmeta.worker_schedule_tick
WHERE schedule_code = 'psi5_route_incident_automation_15m'
   OR task_name = 'route_incident_automation';

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'psi5_route_incident_automation_15m'
   OR task_name = 'route_incident_automation';

DROP TABLE IF EXISTS qmeta.source_route_incident_action CASCADE;
