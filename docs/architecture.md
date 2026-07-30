# QData Architecture

![QData architecture](assets/qdata-architecture.svg)

The architecture is deliberately built around a free-source research route:

- Free/public data candidates are collected through provider adapters.
- Ingestion normalizes data into quant-ready datasets such as daily bars, adjustment factors, trading calendars, PIT fundamentals and events.
- PostgreSQL stores metadata, point-in-time records, audit trails and worker schedules.
- ClickHouse stores time-series market and factor data.
- Governance modules score source reliability, admission status, recovery actions and scheduler health.
- The project exposes research workflows through a Python SDK, REST API, admin console and research demos.
