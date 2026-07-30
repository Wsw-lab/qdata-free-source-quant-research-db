from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata import Client


def main() -> None:
    with Client(backend="sql", default_format="records") as client:
        print("== SQL securities ==")
        print(client.get_security_master(
            symbols=["600519.SH"],
            asof_date="2024-12-31",
        ))

        print("\n== SQL calendar ==")
        print(client.get_trading_calendar(
            exchange="SH",
            start_date="2024-01-02",
            end_date="2024-01-03",
        ))

        print("\n== SQL prices ==")
        print(client.get_price(
            symbols=["600519.SH", "000001.SZ"],
            start_date="2024-01-02",
            end_date="2024-01-03",
            adjust="forward",
        ))

        print("\n== SQL PIT fundamentals ==")
        print(client.get_fundamental_asof(
            symbols=["600519.SH"],
            fields=["revenue", "net_profit_parent", "roe_ttm"],
            asof_date="2021-06-30",
        ))

        print("\n== SQL index members ==")
        print(client.get_index_members_asof(
            index_code="000300.SH",
            asof_date="2024-06-28",
        ))

        print("\n== SQL industry ==")
        print(client.get_industry_asof(
            symbols=["600519.SH"],
            industry_system="sw",
            level=1,
            asof_date="2024-12-31",
        ))

        print("\n== SQL universe factors ==")
        print(client.get_factor(
            factors=["momentum_20d", "roe_ttm"],
            universe="hs300",
            start_date="2024-01-02",
            end_date="2024-01-02",
            format="wide",
        ))

        print("\n== SQL health ==")
        print(client.get_dataset_health(
            dataset_code="daily_bar",
            start_date="2024-01-02",
            end_date="2024-01-02",
        ))


if __name__ == "__main__":
    main()
