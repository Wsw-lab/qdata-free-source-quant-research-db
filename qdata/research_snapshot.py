"""Build and verify deterministic ``research_snapshot_v1`` bundles.

The snapshot format deliberately uses only CSV and canonical JSON so that a
consumer can verify it without a database server or an optional dataframe
dependency.  A build never overwrites an existing directory.  Repeating the
same build at the same path is idempotent only when the existing snapshot
verifies and has the same content-derived snapshot id.

This module is intentionally narrow: it defines the interchange contract
between QData and a research consumer.  It does not claim that an upstream
provider is point-in-time correct; it makes the provider's cutoff and
``available_at`` assertions explicit and independently verifiable.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA_VERSION = "research_snapshot_v1"
MANIFEST_FILENAME = "manifest.json"


class ResearchSnapshotError(Exception):
    """Base class for research snapshot errors."""


class SnapshotValidationError(ResearchSnapshotError):
    """Raised when input rows or manifest metadata violate the contract."""


class SnapshotVerificationError(ResearchSnapshotError):
    """Raised when an on-disk snapshot cannot be independently verified."""


class SnapshotImmutableError(ResearchSnapshotError):
    """Raised when a build would replace different existing content."""


@dataclass(frozen=True)
class DatasetContract:
    columns: tuple[str, ...]
    primary_key: tuple[str, ...]
    date_field: str
    kinds: Mapping[str, str]
    nullable: frozenset[str] = frozenset()


DATASET_CONTRACTS: Mapping[str, DatasetContract] = {
    "daily_bar": DatasetContract(
        columns=(
            "symbol",
            "trade_date",
            "open_raw",
            "high_raw",
            "low_raw",
            "close_raw",
            "close_adjusted",
            "adjustment_factor",
            "volume",
            "amount",
            "available_at",
            "source_id",
            "batch_id",
            "data_version",
        ),
        primary_key=("symbol", "trade_date"),
        date_field="trade_date",
        kinds={
            "symbol": "string",
            "trade_date": "date",
            "open_raw": "number",
            "high_raw": "number",
            "low_raw": "number",
            "close_raw": "number",
            "close_adjusted": "number",
            "adjustment_factor": "number",
            "volume": "number",
            "amount": "number",
            "available_at": "timestamp",
            "source_id": "string",
            "batch_id": "string",
            "data_version": "string",
        },
    ),
    "tradability": DatasetContract(
        columns=(
            "symbol",
            "trade_date",
            "is_st",
            "is_suspended",
            "limit_up",
            "limit_down",
            "is_limit_up",
            "is_limit_down",
            "can_buy",
            "can_sell",
            "lot_size",
            "t_plus_one",
            "available_at",
        ),
        primary_key=("symbol", "trade_date"),
        date_field="trade_date",
        kinds={
            "symbol": "string",
            "trade_date": "date",
            "is_st": "boolean",
            "is_suspended": "boolean",
            "limit_up": "number",
            "limit_down": "number",
            "is_limit_up": "boolean",
            "is_limit_down": "boolean",
            "can_buy": "boolean",
            "can_sell": "boolean",
            "lot_size": "integer",
            "t_plus_one": "boolean",
            "available_at": "timestamp",
        },
        nullable=frozenset({"limit_up", "limit_down"}),
    ),
    "security_membership": DatasetContract(
        columns=(
            "symbol",
            "list_date",
            "delist_date",
            "valid_from",
            "valid_to",
            "board",
            "asset_type",
            "status",
            "available_at",
        ),
        primary_key=("symbol", "valid_from"),
        date_field="valid_from",
        kinds={
            "symbol": "string",
            "list_date": "date",
            "delist_date": "date",
            "valid_from": "date",
            "valid_to": "date",
            "board": "string",
            "asset_type": "string",
            "status": "string",
            "available_at": "timestamp",
        },
        nullable=frozenset({"delist_date", "valid_to"}),
    ),
    "fundamental_pit": DatasetContract(
        columns=(
            "symbol",
            "report_period_end",
            "field_name",
            "field_value",
            "published_at",
            "first_seen_at",
            "available_at",
            "revision_id",
            "is_restated",
            "source_id",
        ),
        primary_key=("symbol", "report_period_end", "field_name", "revision_id"),
        date_field="report_period_end",
        kinds={
            "symbol": "string",
            "report_period_end": "date",
            "field_name": "string",
            "field_value": "number",
            "published_at": "timestamp",
            "first_seen_at": "timestamp",
            "available_at": "timestamp",
            "revision_id": "string",
            "is_restated": "boolean",
            "source_id": "string",
        },
    ),
}


_MANIFEST_KEYS = {
    "schema_version",
    "snapshot_id",
    "format",
    "cutoff_ts",
    "timezone",
    "source",
    "data_version",
    "quality_status",
    "datasets",
}


def build_research_snapshot(
    output_dir: str | os.PathLike[str],
    datasets: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    cutoff_ts: str | datetime,
    timezone_name: str,
    source: str,
    data_version: str,
    quality_status: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an immutable deterministic snapshot and return its manifest.

    A staged snapshot is verified before publication and its manifest is moved
    last. Existing content is never replaced. If the exact same snapshot
    already exists, it is verified and returned unchanged.
    """

    destination = Path(output_dir)
    cutoff = _parse_timestamp(cutoff_ts, "cutoff_ts")
    canonical_cutoff = _format_timestamp(cutoff)
    canonical_timezone = _validate_timezone(timezone_name)
    canonical_source = _required_string(source, "source")
    canonical_version = _required_string(data_version, "data_version")
    canonical_quality = _normalize_quality_status(quality_status)

    rows_by_dataset = _canonicalize_datasets(
        datasets,
        cutoff=cutoff,
        data_version=canonical_version,
    )
    _validate_cross_dataset_contract(rows_by_dataset)

    file_payloads: dict[str, bytes] = {}
    dataset_metadata: dict[str, dict[str, Any]] = {}
    for name, contract in DATASET_CONTRACTS.items():
        rows = rows_by_dataset[name]
        payload = _csv_bytes(contract, rows)
        file_payloads[name] = payload
        dataset_metadata[name] = _dataset_metadata(name, contract, rows, payload)

    manifest_without_id: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "format": "csv+canonical-json",
        "cutoff_ts": canonical_cutoff,
        "timezone": canonical_timezone,
        "source": canonical_source,
        "data_version": canonical_version,
        "quality_status": canonical_quality,
        "datasets": dataset_metadata,
    }
    snapshot_id = "sha256:" + _sha256(_canonical_json_bytes(manifest_without_id))
    manifest = dict(manifest_without_id)
    manifest["snapshot_id"] = snapshot_id
    manifest_payload = _canonical_json_bytes(manifest)

    if destination.exists() or destination.is_symlink():
        try:
            existing = verify_research_snapshot(destination)
        except ResearchSnapshotError as exc:
            raise SnapshotImmutableError(
                f"refusing to replace existing unverifiable snapshot: {destination}"
            ) from exc
        if existing["snapshot_id"] != snapshot_id:
            raise SnapshotImmutableError(
                "refusing to replace an existing snapshot with different content: "
                f"{destination}"
            )
        return existing

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    try:
        for name, payload in file_payloads.items():
            (staging / f"{name}.csv").write_bytes(payload)
        (staging / MANIFEST_FILENAME).write_bytes(manifest_payload)
        verified = verify_research_snapshot(staging)
        try:
            # Reserving the final name with mkdir is deliberately used instead
            # of os.rename: POSIX rename may replace an existing empty
            # directory.  This preserves the no-overwrite guarantee even when
            # two builders race for the same destination.
            destination.mkdir()
        except FileExistsError as exc:
            try:
                existing = verify_research_snapshot(destination)
            except ResearchSnapshotError as verify_exc:
                raise SnapshotImmutableError(
                    f"snapshot destination appeared during publication: {destination}"
                ) from verify_exc
            if existing["snapshot_id"] != snapshot_id:
                raise SnapshotImmutableError(
                    "snapshot destination appeared with different content: "
                    f"{destination}"
                ) from exc
            return existing
        published_names: list[str] = []
        try:
            # Publish the manifest last. A concurrent verifier either observes
            # an incomplete bundle and fails closed, or the complete bundle.
            for filename in sorted(
                expected
                for expected in _expected_snapshot_filenames()
                if expected != MANIFEST_FILENAME
            ):
                (staging / filename).replace(destination / filename)
                published_names.append(filename)
            (staging / MANIFEST_FILENAME).replace(destination / MANIFEST_FILENAME)
            published_names.append(MANIFEST_FILENAME)
        except Exception:
            # Remove only files created by this builder. Never recursively
            # delete content another process may have added.
            for filename in reversed(published_names):
                try:
                    (destination / filename).unlink()
                except FileNotFoundError:
                    pass
            try:
                destination.rmdir()
            except OSError:
                pass
            raise
        return verified
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify_research_snapshot(
    snapshot_dir: str | os.PathLike[str],
) -> dict[str, Any]:
    """Verify hashes, manifest, schemas, canonical bytes, and PIT cutoff."""

    root = Path(snapshot_dir)
    if root.is_symlink() or not root.is_dir():
        raise SnapshotVerificationError(f"snapshot path is not a regular directory: {root}")

    expected_names = _expected_snapshot_filenames()
    actual_names = {entry.name for entry in root.iterdir()}
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise SnapshotVerificationError(
            f"snapshot file set mismatch; missing={missing}, extra={extra}"
        )

    manifest_path = root / MANIFEST_FILENAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise SnapshotVerificationError("manifest must be a regular file")
    manifest_payload = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotVerificationError("manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise SnapshotVerificationError("manifest root must be an object")
    if manifest_payload != _canonical_json_bytes(manifest):
        raise SnapshotVerificationError("manifest is not canonical JSON")
    if set(manifest) != _MANIFEST_KEYS:
        raise SnapshotVerificationError("manifest fields do not match the v1 contract")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotVerificationError(
            f"unsupported schema_version: {manifest.get('schema_version')!r}"
        )
    if manifest.get("format") != "csv+canonical-json":
        raise SnapshotVerificationError("unsupported snapshot format")

    try:
        cutoff = _parse_timestamp(manifest.get("cutoff_ts"), "cutoff_ts")
        canonical_cutoff = _format_timestamp(cutoff)
        timezone_name = _validate_timezone(manifest.get("timezone"))
        source = _required_string(manifest.get("source"), "source")
        data_version = _required_string(manifest.get("data_version"), "data_version")
        quality_status = _normalize_quality_status(manifest.get("quality_status"))
    except SnapshotValidationError as exc:
        raise SnapshotVerificationError(str(exc)) from exc
    if manifest["cutoff_ts"] != canonical_cutoff:
        raise SnapshotVerificationError("cutoff_ts is not in canonical UTC form")
    if (
        manifest["timezone"] != timezone_name
        or manifest["source"] != source
        or manifest["data_version"] != data_version
    ):
        raise SnapshotVerificationError(
            "timezone, source, or data_version is not canonical"
        )
    if manifest["quality_status"] != quality_status:
        raise SnapshotVerificationError("quality_status is not canonical")

    manifest_datasets = manifest.get("datasets")
    if not isinstance(manifest_datasets, dict) or set(manifest_datasets) != set(
        DATASET_CONTRACTS
    ):
        raise SnapshotVerificationError("manifest datasets do not match the v1 contract")

    rows_by_dataset: dict[str, list[dict[str, str]]] = {}
    for name, contract in DATASET_CONTRACTS.items():
        file_path = root / f"{name}.csv"
        if file_path.is_symlink() or not file_path.is_file():
            raise SnapshotVerificationError(f"{name} must be a regular file")
        payload = file_path.read_bytes()
        metadata = manifest_datasets[name]
        if not isinstance(metadata, dict):
            raise SnapshotVerificationError(f"manifest metadata for {name} must be an object")
        if metadata.get("sha256") != _sha256(payload):
            raise SnapshotVerificationError(f"SHA256 mismatch for {name}.csv")
        try:
            rows = _read_canonical_csv(name, contract, payload)
            canonical_rows = _canonicalize_rows(
                name,
                contract,
                rows,
                cutoff=cutoff,
                data_version=data_version,
            )
        except SnapshotValidationError as exc:
            raise SnapshotVerificationError(str(exc)) from exc
        canonical_payload = _csv_bytes(contract, canonical_rows)
        if payload != canonical_payload:
            raise SnapshotVerificationError(f"{name}.csv is not canonical")
        expected_metadata = _dataset_metadata(
            name, contract, canonical_rows, canonical_payload
        )
        if metadata != expected_metadata:
            raise SnapshotVerificationError(f"manifest metadata mismatch for {name}")
        rows_by_dataset[name] = canonical_rows

    try:
        _validate_cross_dataset_contract(rows_by_dataset)
    except SnapshotValidationError as exc:
        raise SnapshotVerificationError(str(exc)) from exc

    manifest_without_id = dict(manifest)
    claimed_snapshot_id = manifest_without_id.pop("snapshot_id")
    expected_snapshot_id = "sha256:" + _sha256(
        _canonical_json_bytes(manifest_without_id)
    )
    if claimed_snapshot_id != expected_snapshot_id:
        raise SnapshotVerificationError("snapshot_id does not match manifest content")

    return manifest


def _canonicalize_datasets(
    datasets: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    cutoff: datetime,
    data_version: str,
) -> dict[str, list[dict[str, str]]]:
    if not isinstance(datasets, Mapping):
        raise SnapshotValidationError("datasets must be a mapping")
    names = set(datasets)
    if names != set(DATASET_CONTRACTS):
        missing = sorted(set(DATASET_CONTRACTS) - names, key=str)
        extra = sorted(names - set(DATASET_CONTRACTS), key=str)
        raise SnapshotValidationError(
            f"dataset set mismatch; missing={missing}, extra={extra}"
        )
    return {
        name: _canonicalize_rows(
            name,
            contract,
            list(datasets[name]),
            cutoff=cutoff,
            data_version=data_version,
        )
        for name, contract in DATASET_CONTRACTS.items()
    }


def _canonicalize_rows(
    name: str,
    contract: DatasetContract,
    rows: Sequence[Mapping[str, Any]],
    *,
    cutoff: datetime,
    data_version: str,
) -> list[dict[str, str]]:
    if not rows:
        raise SnapshotValidationError(f"{name} must contain at least one row")

    canonical: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    expected_columns = set(contract.columns)
    for index, raw_row in enumerate(rows, start=1):
        if not isinstance(raw_row, Mapping):
            raise SnapshotValidationError(f"{name} row {index} must be a mapping")
        actual_columns = set(raw_row)
        if actual_columns != expected_columns:
            missing = sorted(expected_columns - actual_columns, key=str)
            extra = sorted(actual_columns - expected_columns, key=str)
            raise SnapshotValidationError(
                f"{name} row {index} fields mismatch; missing={missing}, extra={extra}"
            )

        row: dict[str, str] = {}
        for column in contract.columns:
            row[column] = _canonical_value(
                raw_row[column],
                contract.kinds[column],
                nullable=column in contract.nullable,
                field=f"{name}[{index}].{column}",
            )

        key = tuple(row[column] for column in contract.primary_key)
        if key in seen:
            raise SnapshotValidationError(
                f"duplicate {name} primary key {dict(zip(contract.primary_key, key))}"
            )
        seen.add(key)

        available_at = _parse_timestamp(row["available_at"], f"{name}.available_at")
        if available_at > cutoff:
            raise SnapshotValidationError(
                f"{name} row {index} available_at exceeds cutoff_ts"
            )
        if name == "daily_bar" and row["data_version"] != data_version:
            raise SnapshotValidationError(
                f"daily_bar row {index} data_version does not match manifest"
            )
        _validate_row_semantics(name, row, index)
        canonical.append(row)

    canonical.sort(key=lambda row: tuple(row[field] for field in contract.primary_key))
    return canonical


def _validate_row_semantics(name: str, row: Mapping[str, str], index: int) -> None:
    if name == "daily_bar":
        open_price = Decimal(row["open_raw"])
        high = Decimal(row["high_raw"])
        low = Decimal(row["low_raw"])
        close = Decimal(row["close_raw"])
        if min(open_price, high, low, close, Decimal(row["close_adjusted"])) <= 0:
            raise SnapshotValidationError(f"daily_bar row {index} prices must be positive")
        if high < max(open_price, low, close) or low > min(open_price, high, close):
            raise SnapshotValidationError(f"daily_bar row {index} has invalid OHLC")
        if Decimal(row["adjustment_factor"]) <= 0:
            raise SnapshotValidationError(
                f"daily_bar row {index} adjustment_factor must be positive"
            )
        if Decimal(row["volume"]) < 0 or Decimal(row["amount"]) < 0:
            raise SnapshotValidationError(
                f"daily_bar row {index} volume and amount must be non-negative"
            )
    elif name == "tradability":
        if int(row["lot_size"]) <= 0:
            raise SnapshotValidationError(
                f"tradability row {index} lot_size must be positive"
            )
        for field in ("limit_up", "limit_down"):
            if row[field] and Decimal(row[field]) <= 0:
                raise SnapshotValidationError(
                    f"tradability row {index} {field} must be positive when present"
                )
        if row["is_suspended"] == "true" and (
            row["can_buy"] != "false" or row["can_sell"] != "false"
        ):
            raise SnapshotValidationError(
                f"tradability row {index} suspended security cannot be buyable or sellable"
            )
        if row["is_limit_up"] == "true" and row["can_buy"] != "false":
            raise SnapshotValidationError(
                f"tradability row {index} limit-up security cannot be buyable"
            )
        if row["is_limit_down"] == "true" and row["can_sell"] != "false":
            raise SnapshotValidationError(
                f"tradability row {index} limit-down security cannot be sellable"
            )
    elif name == "security_membership":
        list_date = date.fromisoformat(row["list_date"])
        valid_from = date.fromisoformat(row["valid_from"])
        if valid_from < list_date:
            raise SnapshotValidationError(
                f"security_membership row {index} valid_from precedes list_date"
            )
        if row["delist_date"] and date.fromisoformat(row["delist_date"]) < list_date:
            raise SnapshotValidationError(
                f"security_membership row {index} delist_date precedes list_date"
            )
        if row["valid_to"] and date.fromisoformat(row["valid_to"]) < valid_from:
            raise SnapshotValidationError(
                f"security_membership row {index} valid_to precedes valid_from"
            )
    elif name == "fundamental_pit":
        published_at = _parse_timestamp(row["published_at"], "published_at")
        first_seen_at = _parse_timestamp(row["first_seen_at"], "first_seen_at")
        available_at = _parse_timestamp(row["available_at"], "available_at")
        if available_at < max(published_at, first_seen_at):
            raise SnapshotValidationError(
                f"fundamental_pit row {index} available_at precedes publication or ingestion"
            )


def _validate_cross_dataset_contract(
    rows_by_dataset: Mapping[str, Sequence[Mapping[str, str]]],
) -> None:
    daily_keys = {
        (row["symbol"], row["trade_date"]) for row in rows_by_dataset["daily_bar"]
    }
    tradability_keys = {
        (row["symbol"], row["trade_date"])
        for row in rows_by_dataset["tradability"]
    }
    if daily_keys != tradability_keys:
        missing = sorted(daily_keys - tradability_keys)[:5]
        extra = sorted(tradability_keys - daily_keys)[:5]
        raise SnapshotValidationError(
            "daily_bar and tradability keys must match exactly; "
            f"missing_tradability={missing}, extra_tradability={extra}"
        )

    memberships: dict[str, list[tuple[date, date | None]]] = {}
    for row in rows_by_dataset["security_membership"]:
        memberships.setdefault(row["symbol"], []).append(
            (
                date.fromisoformat(row["valid_from"]),
                date.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
            )
        )

    for symbol, trade_date_text in sorted(daily_keys):
        trade_date = date.fromisoformat(trade_date_text)
        intervals = memberships.get(symbol, [])
        is_covered = any(
            start <= trade_date and (end is None or trade_date <= end)
            for start, end in intervals
        )
        if not is_covered:
            raise SnapshotValidationError(
                f"daily_bar key {(symbol, trade_date_text)} has no active security membership"
            )
    for row in rows_by_dataset["fundamental_pit"]:
        if row["symbol"] not in memberships:
            raise SnapshotValidationError(
                f"fundamental_pit symbol {row['symbol']} has no security membership"
            )


def _dataset_metadata(
    name: str,
    contract: DatasetContract,
    rows: Sequence[Mapping[str, str]],
    payload: bytes,
) -> dict[str, Any]:
    dates = [row[contract.date_field] for row in rows]
    return {
        "path": f"{name}.csv",
        "sha256": _sha256(payload),
        "row_count": len(rows),
        "columns": list(contract.columns),
        "primary_key": list(contract.primary_key),
        "date_field": contract.date_field,
        "date_range": {"start": min(dates), "end": max(dates)},
    }


def _read_canonical_csv(
    name: str,
    contract: DatasetContract,
    payload: bytes,
) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SnapshotValidationError(f"{name}.csv is not UTF-8") from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames != list(contract.columns):
            raise SnapshotValidationError(f"{name}.csv header does not match contract")
        rows = list(reader)
    except csv.Error as exc:
        raise SnapshotValidationError(f"{name}.csv is malformed") from exc
    if any(None in row for row in rows):
        raise SnapshotValidationError(f"{name}.csv contains extra unnamed columns")
    return rows


def _csv_bytes(
    contract: DatasetContract,
    rows: Sequence[Mapping[str, str]],
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(contract.columns),
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row[column] for column in contract.columns})
    return output.getvalue().encode("utf-8")


def _canonical_value(value: Any, kind: str, *, nullable: bool, field: str) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        if nullable:
            return ""
        raise SnapshotValidationError(f"missing required field {field}")
    if kind == "string":
        return _required_string(value, field)
    if kind == "date":
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except (TypeError, ValueError) as exc:
            raise SnapshotValidationError(f"{field} must be an ISO date") from exc
    if kind == "timestamp":
        return _format_timestamp(_parse_timestamp(value, field))
    if kind == "boolean":
        if isinstance(value, bool):
            return "true" if value else "false"
        normalized = str(value).strip().lower()
        if normalized in {"true", "1"}:
            return "true"
        if normalized in {"false", "0"}:
            return "false"
        raise SnapshotValidationError(f"{field} must be boolean")
    if kind in {"number", "integer"}:
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as exc:
            raise SnapshotValidationError(f"{field} must be numeric") from exc
        if not number.is_finite():
            raise SnapshotValidationError(f"{field} must be finite")
        if kind == "integer":
            integral = number.to_integral_value()
            if number != integral:
                raise SnapshotValidationError(f"{field} must be an integer")
            return str(integral)
        if number == 0:
            return "0"
        normalized_number = number.normalize()
        rendered = format(normalized_number, "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    raise SnapshotValidationError(f"unknown field type {kind!r} for {field}")


def _parse_timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except (TypeError, ValueError) as exc:
            raise SnapshotValidationError(
                f"{field} must be an ISO timestamp with an explicit UTC offset"
            ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotValidationError(
            f"{field} must be an ISO timestamp with an explicit UTC offset"
        )
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_timezone(value: Any) -> str:
    name = _required_string(value, "timezone")
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise SnapshotValidationError(f"unknown IANA timezone: {name}") from exc
    return name


def _normalize_quality_status(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("quality_status must be an object")
    if set(value) != {"status", "error_count", "warning_count"}:
        raise SnapshotValidationError(
            "quality_status requires exactly status, error_count, and warning_count"
        )
    status = _required_string(value["status"], "quality_status.status").lower()
    if status != "passed":
        raise SnapshotValidationError("a research snapshot requires passed quality status")
    errors = _quality_count(value["error_count"], "quality_status.error_count")
    warnings = _quality_count(value["warning_count"], "quality_status.warning_count")
    if errors != 0 or warnings < 0:
        raise SnapshotValidationError(
            "passed quality_status requires zero errors and non-negative warnings"
        )
    return {"status": status, "error_count": errors, "warning_count": warnings}


def _quality_count(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise SnapshotValidationError(f"{field} must be an integer")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise SnapshotValidationError(f"{field} must be an integer") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise SnapshotValidationError(f"{field} must be an integer")
    return int(number)


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _expected_snapshot_filenames() -> set[str]:
    """Return the exact regular-file set permitted in a v1 snapshot."""

    return {MANIFEST_FILENAME} | {f"{name}.csv" for name in DATASET_CONTRACTS}


__all__ = [
    "DATASET_CONTRACTS",
    "MANIFEST_FILENAME",
    "SCHEMA_VERSION",
    "ResearchSnapshotError",
    "SnapshotImmutableError",
    "SnapshotValidationError",
    "SnapshotVerificationError",
    "build_research_snapshot",
    "verify_research_snapshot",
]
