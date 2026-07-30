#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.docker/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

detect_applied_postgres_prefix() {
  local marker
  marker="$(docker compose exec -T postgres psql -U qdata -d qdata -At <<'SQL'
SELECT CASE
  WHEN to_regclass('qmeta.vendor_production_source_run') IS NOT NULL THEN '0055'
  WHEN to_regclass('qmeta.source_route_incident_approval_release_preflight') IS NOT NULL THEN '0054'
  WHEN to_regclass('qmeta.source_route_incident_approval_recovery_drill') IS NOT NULL THEN '0053'
  WHEN to_regclass('qmeta.source_route_incident_approval_escalation') IS NOT NULL THEN '0052'
  WHEN to_regclass('qmeta.source_route_incident_approval_command') IS NOT NULL THEN '0051'
  WHEN to_regclass('qmeta.source_route_incident_operation_batch') IS NOT NULL THEN '0050'
  WHEN to_regclass('qmeta.source_route_incident_control_health_snapshot') IS NOT NULL THEN '0049'
  WHEN to_regclass('qmeta.source_route_incident_control') IS NOT NULL THEN '0048'
  WHEN to_regclass('qmeta.source_route_incident_action') IS NOT NULL THEN '0047'
  WHEN to_regclass('qmeta.source_route_circuit_breaker') IS NOT NULL THEN '0046'
  WHEN to_regclass('qmeta.source_route_decision_audit') IS NOT NULL THEN '0045'
  WHEN to_regclass('qmeta.source_route_weight_policy') IS NOT NULL THEN '0044'
  WHEN to_regclass('qmeta.vendor_cost_optimization_snapshot') IS NOT NULL THEN '0043'
  WHEN to_regclass('qmeta.vendor_primary_stability_snapshot') IS NOT NULL THEN '0042'
  WHEN to_regclass('qmeta.vendor_post_promotion_monitor_run') IS NOT NULL THEN '0041'
  WHEN to_regclass('qmeta.vendor_primary_promotion_run') IS NOT NULL THEN '0040'
  WHEN to_regclass('qmeta.vendor_contract_profile') IS NOT NULL THEN '0039'
  WHEN to_regclass('qmeta.free_source_admission_profile') IS NOT NULL THEN '0038'
  WHEN to_regclass('qmeta.free_source_recovery_health_snapshot') IS NOT NULL THEN '0037'
  WHEN to_regclass('qmeta.free_source_recovery_execution') IS NOT NULL THEN '0036'
  WHEN to_regclass('qmeta.free_source_recovery_run') IS NOT NULL THEN '0035'
  WHEN to_regclass('qmeta.free_source_reliability_snapshot') IS NOT NULL THEN '0034'
  WHEN to_regclass('qmeta.free_source_fabric_run') IS NOT NULL THEN '0033'
  WHEN to_regclass('qmeta.vendor_live_pilot_run') IS NOT NULL THEN '0032'
  WHEN to_regclass('qmeta.vendor_live_closure_run') IS NOT NULL THEN '0031'
  WHEN to_regclass('qmeta.vendor_onboarding_run') IS NOT NULL THEN '0030'
  WHEN to_regclass('qmeta.vendor_live_gate_run') IS NOT NULL THEN '0029'
  WHEN to_regclass('qmeta.automation_live_provider_receipt') IS NOT NULL THEN '0028'
  WHEN to_regclass('qmeta.automation_channel_profile') IS NOT NULL THEN '0027'
  WHEN to_regclass('qmeta.automation_external_channel') IS NOT NULL THEN '0026'
  WHEN to_regclass('qmeta.automation_executor_allowlist') IS NOT NULL THEN '0025'
  WHEN to_regclass('qmeta.automation_approval') IS NOT NULL THEN '0024'
  WHEN to_regclass('qmeta.automation_run') IS NOT NULL THEN '0023'
  WHEN to_regclass('qmeta.access_decision_audit') IS NOT NULL THEN '0022'
  WHEN to_regclass('qmeta.strategy_run') IS NOT NULL THEN '0021'
  WHEN to_regclass('qmeta.payment_import_batch') IS NOT NULL THEN '0020'
  WHEN to_regclass('qmeta.runtime_metric_snapshot') IS NOT NULL THEN '0019'
  WHEN to_regclass('qmeta.revenue_reconciliation_run') IS NOT NULL THEN '0018'
  WHEN to_regclass('qmeta.vendor_readiness_review') IS NOT NULL THEN '0017'
  WHEN to_regclass('qmeta.invoice') IS NOT NULL THEN '0016'
  WHEN to_regclass('qmeta.data_product') IS NOT NULL THEN '0015'
  WHEN to_regclass('qmeta.deployment_release') IS NOT NULL THEN '0014'
  WHEN to_regclass('qmeta.worker_schedule') IS NOT NULL THEN '0013'
  WHEN to_regclass('qmeta.worker_run') IS NOT NULL THEN '0012'
  WHEN to_regclass('qmeta.tenant') IS NOT NULL THEN '0011'
  WHEN to_regclass('qmeta.provider_benchmark_suite_run') IS NOT NULL THEN '0010'
  WHEN to_regclass('qmeta.vendor_integration_profile') IS NOT NULL THEN '0009'
  WHEN to_regclass('qmeta.ops_dashboard_snapshot') IS NOT NULL THEN '0008'
  WHEN to_regclass('qmeta.api_request_audit') IS NOT NULL THEN '0007'
  WHEN to_regclass('qmeta.matrix_export_audit') IS NOT NULL THEN '0006'
  WHEN to_regclass('qmeta.pipeline_repair_queue') IS NOT NULL THEN '0005'
  WHEN EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'qmeta'
      AND table_name = 'pipeline_job'
      AND column_name = 'all_market'
  ) THEN '0004'
  WHEN to_regclass('qmeta.pipeline_job') IS NOT NULL THEN '0003'
  ELSE '0000'
END;
SQL
)"
  printf '%s' "$marker"
}

APPLIED_PREFIX="${QDATA_APPLIED_POSTGRES_MIGRATION_PREFIX:-$(detect_applied_postgres_prefix)}"
echo "Detected applied PostgreSQL migration prefix: $APPLIED_PREFIX"

for migration in $(find db/migrations -maxdepth 1 -type f -name '????_postgresql_*.sql' ! -name '0001_postgresql_init.sql' ! -name '*_rollback.sql' | sort); do
  migration_prefix="$(basename "$migration" | cut -d_ -f1)"
  if [[ "$migration_prefix" == "$APPLIED_PREFIX" || "$migration_prefix" < "$APPLIED_PREFIX" ]]; then
    echo "Skipping already-applied PostgreSQL migration: $migration"
    continue
  fi
  echo "Applying PostgreSQL migration: $migration"
  docker compose exec -T postgres psql -U qdata -d qdata -v ON_ERROR_STOP=1 < "$migration" >/dev/null
done
