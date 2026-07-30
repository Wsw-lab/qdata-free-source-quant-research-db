-- Rollback Tau-5 vendor cost optimization metadata.

DELETE FROM qmeta.worker_schedule_tick
WHERE schedule_code = 'tau5_vendor_cost_optimizer_6h'
   OR task_name = 'vendor_cost_optimizer';

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'tau5_vendor_cost_optimizer_6h'
   OR task_name = 'vendor_cost_optimizer';

DROP TABLE IF EXISTS qmeta.vendor_budget_stress_dataset_snapshot CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_route_weight_plan CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_cost_optimization_snapshot CASCADE;
