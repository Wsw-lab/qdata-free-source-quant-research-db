-- Rollback Upsilon-5 route-weight execution metadata.

DELETE FROM qmeta.worker_schedule_tick
WHERE schedule_code = 'upsilon5_vendor_route_weight_executor_1h'
   OR task_name = 'vendor_route_weight_executor';

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'upsilon5_vendor_route_weight_executor_1h'
   OR task_name = 'vendor_route_weight_executor';

DROP TABLE IF EXISTS qmeta.source_route_weight_policy CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_route_weight_rollout_stage CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_route_weight_execution_dataset CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_route_weight_execution_run CASCADE;
