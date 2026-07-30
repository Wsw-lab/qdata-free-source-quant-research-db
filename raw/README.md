# Raw Data Area

`raw/` 用于保存原始数据文件。

目录约定：

```text
raw/
  samples/                         # 本地开发样例 CSV
  vendor/
    provider/
      daily_market/
        trade_date=YYYY-MM-DD/
          security_master.csv
          trading_calendar.csv
          daily_bar.csv
  imports/
    local_csv/
      dataset_code/
        batch_id=YYYYMMDDHHMMSS/
          original_file.csv
```

原则：

- 原始文件只追加，不覆盖。
- 导入脚本会把输入 CSV 复制到 `raw/imports/...`，便于追溯。
- source provider 同步会先把标准化快照写到 `raw/vendor/...`，再复用统一入库链路。
- 标准化和清洗结果写入 PostgreSQL / ClickHouse。
