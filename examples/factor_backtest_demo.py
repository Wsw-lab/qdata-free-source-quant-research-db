from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata import Client


SIGNAL_DATE = "2024-01-02"
HOLD_DATE = "2024-01-03"
UNIVERSE = "hs300"
FACTOR = "momentum_20d"


def run_demo() -> dict[str, Any]:
    """Run a tiny deterministic factor backtest on the mock research backend."""
    client = Client(default_format="records")
    research_rows = build_research_rows(client)
    if len(research_rows) < 2:
        raise RuntimeError("the demo needs at least two tradable symbols")

    ranked = sorted(research_rows, key=lambda row: row[FACTOR], reverse=True)
    long_bucket = [ranked[0]]
    short_bucket = [ranked[-1]]
    benchmark_return = average(row["next_return"] for row in ranked)
    long_return = average(row["next_return"] for row in long_bucket)
    short_return = average(row["next_return"] for row in short_bucket)

    return {
        "universe": UNIVERSE,
        "factor": FACTOR,
        "signal_date": SIGNAL_DATE,
        "hold_date": HOLD_DATE,
        "tradable_symbol_count": len(ranked),
        "long_symbols": [row["symbol"] for row in long_bucket],
        "short_symbols": [row["symbol"] for row in short_bucket],
        "long_return": long_return,
        "short_return": short_return,
        "benchmark_return": benchmark_return,
        "active_return": long_return - benchmark_return,
        "factor_spread": long_return - short_return,
        "research_rows": ranked,
    }


def build_research_rows(client: Client) -> list[dict[str, Any]]:
    tradable = client.get_tradable_universe(
        asof_date=SIGNAL_DATE,
        universe=UNIVERSE,
        min_list_days=120,
        output_format="records",
    )
    symbols = [row["symbol"] for row in tradable]
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
        end_date=HOLD_DATE,
        adjust="forward",
        fields=["close"],
        output_format="records",
    )
    factor_by_symbol = {row["symbol"]: row for row in factors}
    price_by_symbol_date = {(row["symbol"], row["trade_date"]): row["close"] for row in prices}

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        signal_close = price_by_symbol_date.get((symbol, SIGNAL_DATE))
        hold_close = price_by_symbol_date.get((symbol, HOLD_DATE))
        factor_row = factor_by_symbol.get(symbol)
        if signal_close is None or hold_close is None or not factor_row:
            continue
        rows.append(
            {
                "symbol": symbol,
                "signal_close": signal_close,
                "hold_close": hold_close,
                FACTOR: factor_row[FACTOR],
                "roe_ttm": factor_row["roe_ttm"],
                "next_return": hold_close / signal_close - 1.0,
            }
        )
    return rows


def average(values: list[float] | tuple[float, ...] | Any) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def format_report(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "QData factor backtest demo",
            f"universe={result['universe']} factor={result['factor']} signal_date={result['signal_date']} hold_date={result['hold_date']}",
            f"tradable_symbols={result['tradable_symbol_count']} long_bucket={','.join(result['long_symbols'])} short_bucket={','.join(result['short_symbols'])}",
            f"long_return={pct(result['long_return'])} benchmark_return={pct(result['benchmark_return'])} active_return={pct(result['active_return'])} factor_spread={pct(result['factor_spread'])}",
        ]
    )


def pct(value: float) -> str:
    return f"{value * 100:.4f}%"


def main() -> None:
    print(format_report(run_demo()))


if __name__ == "__main__":
    main()
