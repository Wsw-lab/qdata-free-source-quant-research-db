from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata import Client


def main() -> None:
    client = Client(default_format="records")

    print("== securities ==")
    print(
        client.get_security_master(
            symbols=["600519.SH", "000001.SZ"],
            asof_date="2024-12-31",
        )
    )

    print("\n== prices ==")
    print(
        client.get_price(
            symbols=["600519.SH", "000001.SZ"],
            start_date="2024-01-02",
            end_date="2024-01-03",
            adjust="forward",
        )
    )

    print("\n== PIT fundamentals ==")
    print(
        client.get_fundamental_asof(
            symbols=["600519.SH"],
            fields=["revenue", "net_profit_parent", "roe_ttm"],
            asof_date="2021-06-30",
        )
    )

    print("\n== universe factors ==")
    print(
        client.get_factor(
            factors=["momentum_20d", "roe_ttm"],
            universe="hs300",
            start_date="2024-01-02",
            end_date="2024-01-02",
            format="wide",
        )
    )


if __name__ == "__main__":
    main()
