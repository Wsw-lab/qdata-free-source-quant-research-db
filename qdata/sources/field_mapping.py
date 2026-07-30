from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FieldMappingRule:
    external_field: str
    internal_field: str
    transform_rule: str = "identity"
    unit_from: str | None = None
    unit_to: str | None = None
    is_required: bool = False
    priority: int = 100


def normalize_vendor_row(
    row: dict[str, Any],
    field_mapping: dict[str, str] | None = None,
    field_transforms: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not field_mapping:
        return dict(row)
    normalized = dict(row)
    transforms = field_transforms or {}
    for external_field, internal_field in field_mapping.items():
        if external_field not in row:
            continue
        value = row[external_field]
        if _is_missing(value):
            continue
        if internal_field not in normalized or _is_missing(normalized[internal_field]):
            normalized[internal_field] = apply_transform(value, transforms.get(external_field, "identity"))
    return normalized


def apply_transform(value: Any, transform_rule: str) -> Any:
    if _is_missing(value):
        return None
    if transform_rule == "identity":
        return value
    if transform_rule == "date_yyyymmdd":
        text = str(value)
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        if "/" in text:
            return datetime.strptime(text[:10], "%Y/%m/%d").date().isoformat()
        return text[:10]
    numeric = float(value)
    if transform_rule == "volume_hand_to_share":
        return numeric * 100
    if transform_rule == "amount_thousand_to_yuan":
        return numeric * 1000
    if transform_rule == "amount_wan_to_yuan":
        return numeric * 10000
    if transform_rule == "pct_to_ratio":
        return numeric / 100
    if transform_rule == "bps_to_ratio":
        return numeric / 10000
    raise ValueError(f"Unsupported transform_rule: {transform_rule}")


def rules_to_mapping(rules: list[FieldMappingRule]) -> tuple[dict[str, str], dict[str, str]]:
    ordered = sorted(rules, key=lambda item: item.priority)
    return (
        {rule.external_field: rule.internal_field for rule in ordered},
        {rule.external_field: rule.transform_rule for rule in ordered},
    )


def _is_missing(value: Any) -> bool:
    return value is None or value == ""
