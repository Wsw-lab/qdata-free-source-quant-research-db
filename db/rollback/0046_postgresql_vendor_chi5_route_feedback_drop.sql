-- Rollback Chi-5 source-route feedback, circuit breakers and recovery probes.

DELETE FROM qmeta.worker_schedule_tick
WHERE schedule_code = 'chi5_source_route_feedback_15m'
   OR task_name = 'source_route_feedback_monitor';

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'chi5_source_route_feedback_15m'
   OR task_name = 'source_route_feedback_monitor';

ALTER TABLE qmeta.source_route_circuit_breaker
    DROP CONSTRAINT IF EXISTS source_route_circuit_breaker_last_probe_fk;

DROP TABLE IF EXISTS qmeta.source_route_recovery_probe CASCADE;
DROP TABLE IF EXISTS qmeta.source_route_circuit_breaker CASCADE;
DROP TABLE IF EXISTS qmeta.source_route_health_snapshot CASCADE;
