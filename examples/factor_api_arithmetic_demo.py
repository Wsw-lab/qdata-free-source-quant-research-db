from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata import Client


SIGNAL_DATE = "2024-01-02"
REFERENCE_DATE = "2024-01-03"
UNIVERSE = "hs300"
FACTOR = "momentum_20d"


def run_demo() -> dict[str, Any]:
    """Run deterministic next-session adjusted reference arithmetic.

    The factor is treated as an after-close signal on ``SIGNAL_DATE``. The
    next session's forward-adjusted open and close are reference values only.
    No order, execution, next-session tradability check, or backtest is modeled.
    """
    client = Client(default_format="records")
    research_rows = build_research_rows(client)
    if len(research_rows) < 2:
        raise RuntimeError("the demo needs at least two signal-universe symbols")

    ranked = sorted(research_rows, key=lambda row: row[FACTOR], reverse=True)
    highest_factor_group = [ranked[0]]
    lowest_factor_group = [ranked[-1]]
    universe_mean_marked_change = average(row["marked_change"] for row in ranked)
    highest_factor_marked_change = average(
        row["marked_change"] for row in highest_factor_group
    )
    lowest_factor_marked_change = average(
        row["marked_change"] for row in lowest_factor_group
    )

    return {
        "universe": UNIVERSE,
        "factor": FACTOR,
        "signal_date": SIGNAL_DATE,
        "reference_date": REFERENCE_DATE,
        "signal_timing": "after_close",
        "reference_timing": "next_session_forward_adjusted_open_to_close",
        "next_session_tradability_verified": False,
        "signal_universe_symbol_count": len(ranked),
        "highest_factor_symbols": [row["symbol"] for row in highest_factor_group],
        "lowest_factor_symbols": [row["symbol"] for row in lowest_factor_group],
        "highest_factor_marked_change": highest_factor_marked_change,
        "lowest_factor_marked_change": lowest_factor_marked_change,
        "universe_mean_marked_change": universe_mean_marked_change,
        "highest_minus_universe_marked_change": (
            highest_factor_marked_change - universe_mean_marked_change
        ),
        "highest_minus_lowest_marked_change": (
            highest_factor_marked_change - lowest_factor_marked_change
        ),
        "research_rows": ranked,
    }


def build_research_rows(client: Client) -> list[dict[str, Any]]:
    signal_universe = client.get_tradable_universe(
        asof_date=SIGNAL_DATE,
        universe=UNIVERSE,
        min_list_days=120,
        output_format="records",
    )
    symbols = [row["symbol"] for row in signal_universe]
    factors = client.get_factor(
        factors=[FACTOR, "roe_ttm"],
        symbols=symbols,
        start_date=SIGNAL_DATE,
        end_date=SIGNAL_DATE,
        format="wide",
        output_format="records",
    )
    prices = client.get_price(
        symbols=symbols,
        start_date=SIGNAL_DATE,
        end_date=REFERENCE_DATE,
        adjust="forward",
        fields=["open", "close"],
        output_format="records",
    )
    factor_by_symbol = {row["symbol"]: row for row in factors}
    price_by_symbol_date = {(row["symbol"], row["trade_date"]): row for row in prices}

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        reference_bar = price_by_symbol_date.get((symbol, REFERENCE_DATE))
        factor_row = factor_by_symbol.get(symbol)
        if not reference_bar or not factor_row:
            continue
        adjusted_open_reference = reference_bar.get("open")
        adjusted_close_mark = reference_bar.get("close")
        if adjusted_open_reference is None or adjusted_close_mark is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "adjusted_open_reference": adjusted_open_reference,
                "adjusted_close_mark": adjusted_close_mark,
                FACTOR: factor_row[FACTOR],
                "roe_ttm": factor_row["roe_ttm"],
                "marked_change": (
                    adjusted_close_mark / adjusted_open_reference - 1.0
                ),
            }
        )
    return rows


def average(values: list[float] | tuple[float, ...] | Any) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def format_report(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "QData factor API arithmetic demo",
            f"universe={result['universe']} factor={result['factor']} signal_date={result['signal_date']} reference_date={result['reference_date']}",
            f"signal_timing={result['signal_timing']} reference_timing={result['reference_timing']}",
            f"signal_universe_symbols={result['signal_universe_symbol_count']} highest_factor={','.join(result['highest_factor_symbols'])} lowest_factor={','.join(result['lowest_factor_symbols'])}",
            f"highest_factor_marked_change={pct(result['highest_factor_marked_change'])} universe_mean_marked_change={pct(result['universe_mean_marked_change'])} highest_minus_universe_marked_change={pct(result['highest_minus_universe_marked_change'])} highest_minus_lowest_marked_change={pct(result['highest_minus_lowest_marked_change'])}",
            "next_session_tradability_verified=false adjusted_reference_only=true",
        ]
    )


def pct(value: float) -> str:
    return f"{value * 100:.4f}%"


def main() -> None:
    print(format_report(run_demo()))


if __name__ == "__main__":
    main()
