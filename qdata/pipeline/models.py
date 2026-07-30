from __future__ import annotations

from dataclasses import dataclass, field

from qdata.exceptions import QDataValidationError


@dataclass(frozen=True)
class PipelineJobConfig:
    job_code: str
    provider: str
    dataset_code: str = "daily_bar"
    frequency: str = "daily"
    symbols: list[str] = field(default_factory=list)
    provider_config: dict = field(default_factory=dict)
    raw_root: str = "raw"
    strict_quality: bool = True
    retry_limit: int = 1
    all_market: bool = False
    batch_size: int = 0
    max_symbols: int | None = None
    min_completeness: float = 1.0
    skip_closed_days: bool = True
    sleep_seconds: float = 0
    schedule_timezone: str = "Asia/Shanghai"

    def __post_init__(self) -> None:
        if self.retry_limit < 0:
            raise QDataValidationError("retry_limit must be greater than or equal to 0")
        if self.batch_size < 0:
            raise QDataValidationError("batch_size must be greater than or equal to 0")
        if self.max_symbols is not None and self.max_symbols <= 0:
            raise QDataValidationError("max_symbols must be greater than 0")
        if self.min_completeness < 0 or self.min_completeness > 1:
            raise QDataValidationError("min_completeness must be between 0 and 1")
        if self.sleep_seconds < 0:
            raise QDataValidationError("sleep_seconds must be greater than or equal to 0")

    def normalized_symbols(self) -> list[str]:
        return [symbol.strip().upper() for symbol in self.symbols if symbol.strip()]


@dataclass(frozen=True)
class PipelineJobRecord:
    job_id: int
    job_code: str
    provider: str
    dataset_code: str
    retry_limit: int


@dataclass(frozen=True)
class PipelineRunResult:
    job_code: str
    run_id: int | None
    trade_date: str
    attempt: int
    status: str
    row_count: int = 0
    quality_passed: bool | None = None
    error_count: int = 0
    warning_count: int = 0
    expected_row_count: int | None = None
    missing_count: int = 0
    missing_symbols: list[str] = field(default_factory=list)
    completeness_rate: float | None = None
    expected_by_exchange: dict = field(default_factory=dict)
    actual_by_exchange: dict = field(default_factory=dict)
    missing_by_exchange: dict = field(default_factory=dict)
    missing_explanations: dict = field(default_factory=dict)
    batch_count: int = 1
    all_market: bool = False
    repair_status: str = "none"
    raw_paths: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None
    skipped_reason: str | None = None
