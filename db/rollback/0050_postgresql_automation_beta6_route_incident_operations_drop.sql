-- Roll back Beta-6 route incident operation queue artifacts.

DELETE FROM qmeta.worker_schedule_tick
WHERE schedule_code = 'beta6_route_incident_operations_30m'
   OR task_name = 'route_incident_operations';

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'beta6_route_incident_operations_30m'
   OR task_name = 'route_incident_operations';

DELETE FROM qmeta.worker_task_run
WHERE task_name = 'route_incident_operations';

DROP TABLE IF EXISTS qmeta.source_route_incident_operation_item CASCADE;
DROP TABLE IF EXISTS qmeta.source_route_incident_operation_batch CASCADE;
