-- Roll back Omega-5 route incident control table and schedule.

DELETE FROM qmeta.worker_schedule_tick
WHERE schedule_code = 'omega5_route_incident_control_15m'
   OR task_name = 'route_incident_control';

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'omega5_route_incident_control_15m'
   OR task_name = 'route_incident_control';

DROP TABLE IF EXISTS qmeta.source_route_incident_control CASCADE;
