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
Snapshot artifacts are data-contract evidence, not strategy or performance
evidence.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA_VERSION = "research_snapshot_v1"
MANIFEST_FILENAME = "manifest.json"
ARTIFACT_NOTICE = (
    "Research data contract artifact; not strategy or performance evidence."
)


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
            "bar_end_at",
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
            "bar_end_at": "timestamp",
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
    "artifact_notice",
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
    artifact_notice: str = ARTIFACT_NOTICE,
) -> dict[str, Any]:
    """Build an immutable deterministic snapshot and return its manifest.

    A staged snapshot is verified before publication and its manifest is created
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
    canonical_notice = _required_string(artifact_notice, "artifact_notice")

    rows_by_dataset = _canonicalize_datasets(
        datasets,
        cutoff=cutoff,
        data_version=canonical_version,
        snapshot_timezone=ZoneInfo(canonical_timezone),
    )
    _validate_cross_dataset_contract(rows_by_dataset)
    _validate_signal_availability_dates(
        rows_by_dataset, ZoneInfo(canonical_timezone)
    )

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
        "artifact_notice": canonical_notice,
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
        verify_research_snapshot(staging)
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
        publication_payloads = {
            f"{name}.csv": payload for name, payload in file_payloads.items()
        }
        publication_payloads[MANIFEST_FILENAME] = manifest_payload
        _publish_exclusive_files(destination, publication_payloads)
        # Verify the final directory independently. Staging verification cannot
        # prove that publication preserved file identities. Once the final
        # directory has been reserved, failures deliberately leave every entry
        # untouched for operator inspection; a future build refuses to replace
        # the incomplete directory.
        return verify_research_snapshot(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify_research_snapshot(
    snapshot_dir: str | os.PathLike[str],
) -> dict[str, Any]:
    """Verify hashes, manifest, schemas, canonical bytes, and PIT cutoff."""

    root = Path(snapshot_dir)
    directory_fd, directory_identity = _open_regular_directory(root)
    file_fds: dict[str, int] = {}
    try:
        payloads, file_fds, file_identities = _read_snapshot_payloads(directory_fd)
        manifest_payload = payloads[MANIFEST_FILENAME]
        try:
            manifest = json.loads(manifest_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotVerificationError(
                "manifest is not valid UTF-8 JSON"
            ) from exc
        if not isinstance(manifest, dict):
            raise SnapshotVerificationError("manifest root must be an object")
        if manifest_payload != _canonical_json_bytes(manifest):
            raise SnapshotVerificationError("manifest is not canonical JSON")
        if set(manifest) != _MANIFEST_KEYS:
            raise SnapshotVerificationError(
                "manifest fields do not match the v1 contract"
            )
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
            data_version = _required_string(
                manifest.get("data_version"), "data_version"
            )
            quality_status = _normalize_quality_status(
                manifest.get("quality_status")
            )
            artifact_notice = _required_string(
                manifest.get("artifact_notice"), "artifact_notice"
            )
        except SnapshotValidationError as exc:
            raise SnapshotVerificationError(str(exc)) from exc
        if manifest["cutoff_ts"] != canonical_cutoff:
            raise SnapshotVerificationError("cutoff_ts is not in canonical UTC form")
        if (
            manifest["timezone"] != timezone_name
            or manifest["source"] != source
            or manifest["data_version"] != data_version
            or manifest["artifact_notice"] != artifact_notice
        ):
            raise SnapshotVerificationError(
                "timezone, source, data_version, or artifact_notice is not canonical"
            )
        if manifest["quality_status"] != quality_status:
            raise SnapshotVerificationError("quality_status is not canonical")

        manifest_datasets = manifest.get("datasets")
        if not isinstance(manifest_datasets, dict) or set(manifest_datasets) != set(
            DATASET_CONTRACTS
        ):
            raise SnapshotVerificationError(
                "manifest datasets do not match the v1 contract"
            )

        rows_by_dataset: dict[str, list[dict[str, str]]] = {}
        for name, contract in DATASET_CONTRACTS.items():
            payload = payloads[f"{name}.csv"]
            metadata = manifest_datasets[name]
            if not isinstance(metadata, dict):
                raise SnapshotVerificationError(
                    f"manifest metadata for {name} must be an object"
                )
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
                    snapshot_timezone=ZoneInfo(timezone_name),
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
                raise SnapshotVerificationError(
                    f"manifest metadata mismatch for {name}"
                )
            rows_by_dataset[name] = canonical_rows

        try:
            _validate_cross_dataset_contract(rows_by_dataset)
            _validate_signal_availability_dates(
                rows_by_dataset, ZoneInfo(timezone_name)
            )
        except SnapshotValidationError as exc:
            raise SnapshotVerificationError(str(exc)) from exc

        manifest_without_id = dict(manifest)
        claimed_snapshot_id = manifest_without_id.pop("snapshot_id")
        expected_snapshot_id = "sha256:" + _sha256(
            _canonical_json_bytes(manifest_without_id)
        )
        if claimed_snapshot_id != expected_snapshot_id:
            raise SnapshotVerificationError(
                "snapshot_id does not match manifest content"
            )

        _recheck_snapshot_contents(
            root,
            directory_fd,
            directory_identity=directory_identity,
            file_fds=file_fds,
            file_identities=file_identities,
            initial_payloads=payloads,
        )
        return manifest
    finally:
        for file_fd in file_fds.values():
            os.close(file_fd)
        os.close(directory_fd)


_DirectoryIdentity = tuple[int, int, int, int]
_FileIdentity = tuple[int, int, int, int, int]


def _open_regular_directory(path: Path) -> tuple[int, _DirectoryIdentity]:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise SnapshotVerificationError(
            "platform lacks O_NOFOLLOW/O_DIRECTORY; secure verification is unavailable"
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        directory_fd = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise SnapshotVerificationError(
            f"snapshot path is not a regular directory without symlinks: {path}"
        ) from exc
    metadata = os.fstat(directory_fd)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(directory_fd)
        raise SnapshotVerificationError(
            f"snapshot path is not a regular directory: {path}"
        )
    return directory_fd, _directory_identity(metadata)


def _read_snapshot_payloads(
    directory_fd: int,
) -> tuple[dict[str, bytes], dict[str, int], dict[str, _FileIdentity]]:
    expected_names = _expected_snapshot_filenames()
    try:
        actual_names = set(os.listdir(directory_fd))
    except OSError as exc:
        raise SnapshotVerificationError("cannot enumerate snapshot directory") from exc
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise SnapshotVerificationError(
            f"snapshot file set mismatch; missing={missing}, extra={extra}"
        )

    payloads: dict[str, bytes] = {}
    file_fds: dict[str, int] = {}
    identities: dict[str, _FileIdentity] = {}
    try:
        for filename in sorted(expected_names):
            file_fd, payload, identity = _open_and_read_regular_file_at(
                directory_fd, filename
            )
            file_fds[filename] = file_fd
            payloads[filename] = payload
            identities[filename] = identity
        return payloads, file_fds, identities
    except BaseException:
        for file_fd in file_fds.values():
            os.close(file_fd)
        raise


def _open_and_read_regular_file_at(
    directory_fd: int,
    filename: str,
) -> tuple[int, bytes, _FileIdentity]:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        file_fd = os.open(filename, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise SnapshotVerificationError(
            f"{filename} must be a regular file without symlinks"
        ) from exc
    try:
        before = os.fstat(file_fd)
        _validate_open_file_metadata(filename, before)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
        after = os.fstat(file_fd)
        _validate_open_file_metadata(filename, after)
        before_identity = _file_identity(before)
        after_identity = _file_identity(after)
        if before_identity != after_identity or after.st_size != len(payload):
            raise SnapshotVerificationError(
                f"{filename} changed while it was being read"
            )
        return file_fd, payload, after_identity
    except BaseException:
        os.close(file_fd)
        raise


def _validate_open_file_metadata(filename: str, metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise SnapshotVerificationError(f"{filename} must be a regular file")
    if metadata.st_nlink != 1:
        raise SnapshotVerificationError(f"{filename} is exposed through a hard link")


def _file_identity(metadata: os.stat_result) -> _FileIdentity:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _directory_identity(metadata: os.stat_result) -> _DirectoryIdentity:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _recheck_snapshot_contents(
    root: Path,
    directory_fd: int,
    *,
    directory_identity: _DirectoryIdentity,
    file_fds: Mapping[str, int],
    file_identities: Mapping[str, _FileIdentity],
    initial_payloads: Mapping[str, bytes],
) -> None:
    _recheck_directory_state(
        root,
        directory_fd,
        directory_identity=directory_identity,
        expected_names=set(file_identities),
    )
    if set(file_fds) != set(file_identities) or set(initial_payloads) != set(
        file_identities
    ):
        raise SnapshotVerificationError(
            "snapshot file handles changed during verification"
        )

    for filename in sorted(file_identities):
        expected_identity = file_identities[filename]
        file_fd = file_fds[filename]
        try:
            before = os.fstat(file_fd)
            _validate_open_file_metadata(filename, before)
            final_digest, final_size = _hash_open_file(file_fd)
            after = os.fstat(file_fd)
            _validate_open_file_metadata(filename, after)
        except OSError as exc:
            raise SnapshotVerificationError(
                f"{filename} changed during verification"
            ) from exc
        if (
            _file_identity(before) != expected_identity
            or _file_identity(after) != expected_identity
            or final_size != expected_identity[2]
            or final_digest != _sha256(initial_payloads[filename])
        ):
            raise SnapshotVerificationError(
                f"{filename} changed during verification"
            )
        _recheck_directory_entry(
            directory_fd,
            filename=filename,
            expected_identity=expected_identity,
        )

    _recheck_directory_state(
        root,
        directory_fd,
        directory_identity=directory_identity,
        expected_names=set(file_identities),
    )
    for filename in sorted(file_identities):
        expected_identity = file_identities[filename]
        try:
            metadata = os.fstat(file_fds[filename])
            _validate_open_file_metadata(filename, metadata)
        except OSError as exc:
            raise SnapshotVerificationError(
                f"{filename} changed during verification"
            ) from exc
        if _file_identity(metadata) != expected_identity:
            raise SnapshotVerificationError(
                f"{filename} changed during verification"
            )
        _recheck_directory_entry(
            directory_fd,
            filename=filename,
            expected_identity=expected_identity,
        )


def _hash_open_file(file_fd: int) -> tuple[str, int]:
    os.lseek(file_fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total_size = 0
    while True:
        chunk = os.read(file_fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        total_size += len(chunk)
    return digest.hexdigest(), total_size


def _recheck_directory_state(
    root: Path,
    directory_fd: int,
    *,
    directory_identity: _DirectoryIdentity,
    expected_names: set[str],
) -> None:
    try:
        root_metadata = os.stat(root, follow_symlinks=False)
        open_metadata = os.fstat(directory_fd)
    except OSError as exc:
        raise SnapshotVerificationError(
            "snapshot directory changed during verification"
        ) from exc
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or not stat.S_ISDIR(open_metadata.st_mode)
        or _directory_identity(root_metadata) != directory_identity
        or _directory_identity(open_metadata) != directory_identity
    ):
        raise SnapshotVerificationError(
            "snapshot directory changed during verification"
        )
    try:
        current_names = set(os.listdir(directory_fd))
    except OSError as exc:
        raise SnapshotVerificationError(
            "snapshot directory changed during verification"
        ) from exc
    if current_names != expected_names:
        raise SnapshotVerificationError(
            "snapshot file set changed during verification"
        )


def _recheck_directory_entry(
    directory_fd: int,
    *,
    filename: str,
    expected_identity: _FileIdentity,
) -> None:
    try:
        metadata = os.stat(
            filename,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise SnapshotVerificationError(
            f"{filename} changed during verification"
        ) from exc
    _validate_open_file_metadata(filename, metadata)
    if _file_identity(metadata) != expected_identity:
        raise SnapshotVerificationError(
            f"{filename} changed during verification"
        )


def _publish_exclusive_files(
    destination: Path,
    payloads: Mapping[str, bytes],
) -> None:
    try:
        directory_fd, _ = _open_regular_directory(destination)
    except SnapshotVerificationError as exc:
        raise SnapshotImmutableError(
            f"cannot securely publish snapshot at {destination}"
        ) from exc
    ordered_names = sorted(name for name in payloads if name != MANIFEST_FILENAME)
    ordered_names.append(MANIFEST_FILENAME)
    try:
        for filename in ordered_names:
            try:
                _create_exclusive_file_at(
                    directory_fd,
                    filename,
                    payloads[filename],
                )
            except FileExistsError as exc:
                raise SnapshotImmutableError(
                    f"concurrent entry already exists: {filename}"
                ) from exc
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _create_exclusive_file_at(
    directory_fd: int,
    filename: str,
    payload: bytes,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    file_fd = os.open(filename, flags, 0o644, dir_fd=directory_fd)
    try:
        created = os.fstat(file_fd)
        if not stat.S_ISREG(created.st_mode) or created.st_nlink != 1:
            raise SnapshotImmutableError(
                f"exclusive publication did not create a private regular file: {filename}"
            )
        offset = 0
        while offset < len(payload):
            offset += os.write(file_fd, payload[offset:])
        os.fsync(file_fd)
        metadata = os.fstat(file_fd)
        _validate_open_file_metadata(filename, metadata)
        if metadata.st_size != len(payload):
            raise SnapshotImmutableError(
                f"published byte count mismatch for {filename}"
            )
    finally:
        os.close(file_fd)


def _canonicalize_datasets(
    datasets: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    cutoff: datetime,
    data_version: str,
    snapshot_timezone: ZoneInfo,
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
            snapshot_timezone=snapshot_timezone,
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
    snapshot_timezone: ZoneInfo,
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
        _validate_row_semantics(name, row, index, snapshot_timezone)
        canonical.append(row)

    canonical.sort(key=lambda row: tuple(row[field] for field in contract.primary_key))
    return canonical


def _validate_row_semantics(
    name: str,
    row: Mapping[str, str],
    index: int,
    snapshot_timezone: ZoneInfo,
) -> None:
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
        bar_end_at = _parse_timestamp(row["bar_end_at"], "daily_bar.bar_end_at")
        available_at = _parse_timestamp(
            row["available_at"], "daily_bar.available_at"
        )
        if bar_end_at.astimezone(snapshot_timezone).date() != date.fromisoformat(
            row["trade_date"]
        ):
            raise SnapshotValidationError(
                f"daily_bar row {index} bar_end_at date differs from trade_date"
            )
        if available_at < bar_end_at:
            raise SnapshotValidationError(
                f"daily_bar row {index} available_at precedes bar_end_at"
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
        limit_up = Decimal(row["limit_up"]) if row["limit_up"] else None
        limit_down = Decimal(row["limit_down"]) if row["limit_down"] else None
        if limit_up is not None and limit_down is not None and limit_up <= limit_down:
            raise SnapshotValidationError(
                f"tradability row {index} limit_up must exceed limit_down"
            )
        if row["is_limit_up"] == "true" and row["is_limit_down"] == "true":
            raise SnapshotValidationError(
                f"tradability row {index} limit flags are mutually exclusive"
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
        delist_date = (
            date.fromisoformat(row["delist_date"]) if row["delist_date"] else None
        )
        valid_to = date.fromisoformat(row["valid_to"]) if row["valid_to"] else None
        if valid_from < list_date:
            raise SnapshotValidationError(
                f"security_membership row {index} valid_from precedes list_date"
            )
        if delist_date is not None and delist_date < list_date:
            raise SnapshotValidationError(
                f"security_membership row {index} delist_date precedes list_date"
            )
        if valid_to is not None and valid_to <= valid_from:
            raise SnapshotValidationError(
                f"security_membership row {index} valid_to must be after valid_from"
            )
        if delist_date is not None and valid_to is None:
            raise SnapshotValidationError(
                f"security_membership row {index} delist_date requires exclusive valid_to"
            )
        if (
            delist_date is not None
            and valid_to is not None
            and valid_to > delist_date
        ):
            raise SnapshotValidationError(
                f"security_membership row {index} valid_to cannot exceed delist_date"
            )
    elif name == "fundamental_pit":
        published_at = _parse_timestamp(row["published_at"], "published_at")
        first_seen_at = _parse_timestamp(row["first_seen_at"], "first_seen_at")
        available_at = _parse_timestamp(row["available_at"], "available_at")
        report_period_end = date.fromisoformat(row["report_period_end"])
        disclosure_dates = (
            ("published_at", published_at.astimezone(snapshot_timezone).date()),
            ("first_seen_at", first_seen_at.astimezone(snapshot_timezone).date()),
            ("available_at", available_at.astimezone(snapshot_timezone).date()),
        )
        later_than = [
            f"{field} local date {local_date.isoformat()}"
            for field, local_date in disclosure_dates
            if report_period_end > local_date
        ]
        if later_than:
            raise SnapshotValidationError(
                f"fundamental_pit row {index} report_period_end "
                f"{report_period_end.isoformat()} is later than {', '.join(later_than)}"
            )
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

    daily_by_key = {
        (row["symbol"], row["trade_date"]): row
        for row in rows_by_dataset["daily_bar"]
    }
    tradability_by_key = {
        (row["symbol"], row["trade_date"]): row
        for row in rows_by_dataset["tradability"]
    }
    for key in sorted(daily_keys):
        daily = daily_by_key[key]
        tradability = tradability_by_key[key]
        close = Decimal(daily["close_raw"])
        if tradability["is_suspended"] == "true" and (
            Decimal(daily["volume"]) != 0 or Decimal(daily["amount"]) != 0
        ):
            raise SnapshotValidationError(
                f"tradability key {key} suspended daily bar must have zero volume and amount"
            )
        limit_up = (
            Decimal(tradability["limit_up"])
            if tradability["limit_up"] != ""
            else None
        )
        limit_down = (
            Decimal(tradability["limit_down"])
            if tradability["limit_down"] != ""
            else None
        )
        if (limit_up is not None and close > limit_up) or (
            limit_down is not None and close < limit_down
        ):
            raise SnapshotValidationError(
                f"tradability key {key} close_raw is outside declared limit range"
            )
        for direction in ("up", "down"):
            limit_text = tradability[f"limit_{direction}"]
            flag = tradability[f"is_limit_{direction}"] == "true"
            at_limit = limit_text != "" and close == Decimal(limit_text)
            if flag != at_limit:
                raise SnapshotValidationError(
                    f"tradability key {key} is_limit_{direction} disagrees with close_raw"
                )

    memberships: dict[str, list[tuple[date, date | None]]] = {}
    for row in rows_by_dataset["security_membership"]:
        memberships.setdefault(row["symbol"], []).append(
            (
                date.fromisoformat(row["valid_from"]),
                date.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
            )
        )

    for symbol, intervals in memberships.items():
        ordered = sorted(intervals, key=lambda interval: interval[0])
        previous_end: date | None = ordered[0][1]
        for current_start, current_end in ordered[1:]:
            if previous_end is None or current_start < previous_end:
                raise SnapshotValidationError(
                    f"symbol {symbol} has overlapping security membership intervals"
                )
            previous_end = current_end

    market_dates = [
        (date.fromisoformat(trade_date_text), trade_date_text)
        for trade_date_text in sorted({key[1] for key in daily_keys})
    ]
    missing_membership_keys = [
        (symbol, market_date_text)
        for symbol, intervals in sorted(memberships.items())
        for market_date, market_date_text in market_dates
        if any(
            start <= market_date and (end is None or market_date < end)
            for start, end in intervals
        )
        and (symbol, market_date_text) not in daily_keys
    ]
    if missing_membership_keys:
        raise SnapshotValidationError(
            "security_membership has missing explicit daily_bar/tradability "
            "coverage for active symbol/date keys; "
            f"missing={missing_membership_keys[:5]}"
        )

    for symbol, trade_date_text in sorted(daily_keys):
        trade_date = date.fromisoformat(trade_date_text)
        intervals = memberships.get(symbol, [])
        is_covered = any(
            start <= trade_date and (end is None or trade_date < end)
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


def _validate_signal_availability_dates(
    rows_by_dataset: Mapping[str, Sequence[Mapping[str, str]]],
    snapshot_timezone: ZoneInfo,
) -> None:
    daily_by_key = {
        (row["symbol"], row["trade_date"]): row
        for row in rows_by_dataset["daily_bar"]
    }
    tradability_by_key = {
        (row["symbol"], row["trade_date"]): row
        for row in rows_by_dataset["tradability"]
    }
    for key in sorted(daily_by_key):
        daily_available_at = _parse_timestamp(
            daily_by_key[key]["available_at"], "daily_bar.available_at"
        )
        tradability_available_at = _parse_timestamp(
            tradability_by_key[key]["available_at"], "tradability.available_at"
        )
        signal_available_at = max(daily_available_at, tradability_available_at)
        signal_local_date = signal_available_at.astimezone(snapshot_timezone).date()
        trade_date = date.fromisoformat(key[1])
        if signal_local_date != trade_date:
            raise SnapshotValidationError(
                f"daily_bar/tradability key {key} signal_available_at local date "
                f"{signal_local_date.isoformat()} differs from trade_date "
                f"{trade_date.isoformat()}"
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
            return _render_decimal_exact(integral)
        return _render_decimal_exact(number)
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


def _render_decimal_exact(number: Decimal) -> str:
    """Render a finite Decimal without consulting the ambient context."""

    if number.is_zero():
        return "0"
    parts = number.as_tuple()
    digits = list(parts.digits)
    exponent = int(parts.exponent)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in digits)
    decimal_point = len(coefficient) + exponent
    if exponent >= 0:
        plain_length = len(coefficient) + exponent
    elif decimal_point > 0:
        plain_length = len(coefficient) + 1
    else:
        plain_length = 2 + (-decimal_point) + len(coefficient)
    sign = "-" if parts.sign else ""
    if plain_length > 4096:
        mantissa = coefficient[0]
        if len(coefficient) > 1:
            mantissa += "." + coefficient[1:]
        scientific_exponent = exponent + len(coefficient) - 1
        return f"{sign}{mantissa}e{scientific_exponent}"
    if exponent >= 0:
        rendered = coefficient + ("0" * exponent)
    else:
        if decimal_point > 0:
            rendered = coefficient[:decimal_point] + "." + coefficient[decimal_point:]
        else:
            rendered = "0." + ("0" * -decimal_point) + coefficient
    return sign + rendered


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
    "ARTIFACT_NOTICE",
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
