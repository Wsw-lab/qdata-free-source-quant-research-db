-- Roll back Alpha-6 route incident control health snapshots and schedule.

DELETE FROM qmeta.worker_schedule_tick
WHERE schedule_code = 'alpha6_route_incident_control_health_15m'
   OR task_name = 'route_incident_control_health';

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'alpha6_route_incident_control_health_15m'
   OR task_name = 'route_incident_control_health';

DELETE FROM qmeta.worker_task_run
WHERE task_name = 'route_incident_control_health';

DROP TABLE IF EXISTS qmeta.source_route_incident_control_health_snapshot CASCADE;
