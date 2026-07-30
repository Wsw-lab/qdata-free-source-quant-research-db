from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SecurityRecord:
    symbol: str
    name: str
    asset_type: str = "stock"
    currency: str = "CNY"
    list_date: str | None = None
    delist_date: str | None = None
    status: str = "active"

    @property
    def code(self) -> str:
        return self.symbol.split(".")[0]

    @property
    def exchange(self) -> str:
        return self.symbol.split(".")[1]


@dataclass(frozen=True)
class CalendarRecord:
    exchange: str
    trade_date: str
    is_open: bool
    session_type: str = "full_day"
    pretrade_date: str | None = None
    next_trade_date: str | None = None
    open_time: str | None = "09:30"
    close_time: str | None = "15:00"


@dataclass(frozen=True)
class DailyBarRecord:
    symbol: str
    trade_date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    pre_close: float | None
    volume: float | None
    amount: float | None
    vwap: float | None = None
    turnover_rate: float | None = None
    limit_up: float | None = None
    limit_down: float | None = None
    is_suspended: bool = False
    factor_forward: float | None = 1.0
    factor_backward: float | None = 1.0
    ex_right_type: str = "none"

    @property
    def code(self) -> str:
        return self.symbol.split(".")[0]

    @property
    def exchange(self) -> str:
        return self.symbol.split(".")[1]


@dataclass(frozen=True)
class MinuteBarRecord:
    symbol: str
    trade_date: str
    bar_time: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    amount: float | None
    vwap: float | None = None

    @property
    def code(self) -> str:
        return self.symbol.split(".")[0]

    @property
    def exchange(self) -> str:
        return self.symbol.split(".")[1]


@dataclass(frozen=True)
class AdjustmentFactorRecord:
    symbol: str
    trade_date: str
    factor_forward: float | None
    factor_backward: float | None
    ex_right_type: str = "none"

    @property
    def code(self) -> str:
        return self.symbol.split(".")[0]

    @property
    def exchange(self) -> str:
        return self.symbol.split(".")[1]


@dataclass(frozen=True)
class LimitPriceRecord:
    symbol: str
    trade_date: str
    limit_up: float | None
    limit_down: float | None
    limit_rule: str = "unknown"
    is_st: bool = False
    is_new_listing: bool = False

    @property
    def code(self) -> str:
        return self.symbol.split(".")[0]

    @property
    def exchange(self) -> str:
        return self.symbol.split(".")[1]


@dataclass(frozen=True)
class SuspensionRecord:
    symbol: str
    start_time: str
    end_time: str | None = None
    suspension_type: str = "full_day"
    reason: str | None = None

    @property
    def code(self) -> str:
        return self.symbol.split(".")[0]

    @property
    def exchange(self) -> str:
        return self.symbol.split(".")[1]


@dataclass(frozen=True)
class TradableUniverseRecord:
    symbol: str
    trade_date: str
    weight: float | None = None

    @property
    def code(self) -> str:
        return self.symbol.split(".")[0]

    @property
    def exchange(self) -> str:
        return self.symbol.split(".")[1]


@dataclass(frozen=True)
class QualityIssue:
    dataset_code: str
    check_name: str
    severity: str
    message: str
    symbol: str | None = None
    trade_date: str | None = None
    field_name: str | None = None


@dataclass
class QualityReport:
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(issue.severity in {"high", "critical"} for issue in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity in {"high", "critical"})

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity in {"low", "medium"})

    def add(
        self,
        dataset_code: str,
        check_name: str,
        severity: str,
        message: str,
        symbol: str | None = None,
        trade_date: str | None = None,
        field_name: str | None = None,
    ) -> None:
        self.issues.append(
            QualityIssue(
                dataset_code=dataset_code,
                check_name=check_name,
                severity=severity,
                message=message,
                symbol=symbol,
                trade_date=trade_date,
                field_name=field_name,
            )
        )


@dataclass(frozen=True)
class IngestSummary:
    security_count: int
    calendar_count: int
    daily_bar_count: int
    raw_paths: list[str]
    quality_report: QualityReport
