"""Read-only loading and comparison helpers for saved schema45 CAL snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .cal_files import filename_serial
from .cal_engine import CalSnapshot, coefficient_choices, _finite_number, scalar_change
from .offline import parse_cal_payload


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _filename_date(path: Path) -> datetime | None:
    # Keep the exact naming contract centralized in cal_files; the timestamp is
    # parsed only after its serial parser has accepted the complete filename.
    if filename_serial(path) is None:
        return None
    try:
        stamp = path.stem.split("_CAL_", 1)[1]
        return datetime.strptime(stamp, "%Y-%m-%d_%H-%M-%S-%fZ").replace(tzinfo=timezone.utc)
    except (IndexError, ValueError):
        return None


def _sidecar(path: Path, payload_hash: str) -> tuple[dict[str, Any] | None, list[str]]:
    sidecar_path = path.with_suffix(path.suffix + ".json")
    if not sidecar_path.is_file():
        return None, []
    try:
        metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [f"Sidecar could not be read: {exc}"]
    if not isinstance(metadata, dict):
        return None, ["Sidecar is not a JSON object; metadata was ignored."]
    if metadata.get("sha256") != payload_hash:
        return None, ["Sidecar SHA-256 does not match the CAL payload; metadata was ignored."]
    backup = metadata.get("backup")
    if not isinstance(backup, dict):
        return None, ["Hash-matched sidecar has no backup metadata object."]
    return backup, []


def load_snapshots(paths: list[str | Path]) -> list[dict[str, Any]]:
    """Load exact valid CAL:DATA:ALL schema45 files, retaining trusted metadata."""
    if not paths:
        raise ValueError("Select at least one CAL snapshot file.")
    snapshots: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    label_counts: dict[str, int] = {}
    for ordinal, supplied_path in enumerate(paths, 1):
        path = Path(supplied_path)
        display_path = str(path)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"{display_path}: cannot read CAL snapshot: {exc}") from exc
        try:
            report = parse_cal_payload(payload, explain=True)
        except (ValueError, OSError) as exc:
            raise ValueError(f"{display_path}: invalid CAL snapshot: {exc}") from exc
        if report.get("version") != 45 or report.get("bodyLength") != 4924:
            raise ValueError(f"{display_path}: expected schema45 with a 4924-byte body.")
        if report.get("checksumValid") is not True:
            raise ValueError(f"{display_path}: schema45 CAL checksum is invalid.")

        payload_hash = hashlib.sha256(payload).hexdigest()
        backup, warnings = _sidecar(path, payload_hash)
        identity = backup.get("identity") if backup else None
        sidecar_serial = identity.get("serial") if isinstance(identity, dict) else None
        if not isinstance(sidecar_serial, str) or not sidecar_serial.strip():
            sidecar_serial = None
        else:
            sidecar_serial = sidecar_serial.strip()
        file_serial = filename_serial(path)
        serial = sidecar_serial or file_serial
        if sidecar_serial is not None and file_serial is not None and sidecar_serial != file_serial:
            warnings.append(f"Sidecar serial {sidecar_serial} conflicts with filename serial {file_serial}.")

        sidecar_date = _parse_utc(backup.get("savedAtUtc")) if backup else None
        if backup and backup.get("savedAtUtc") is not None and sidecar_date is None:
            warnings.append("Hash-matched sidecar savedAtUtc is invalid or has no timezone.")
        name_date = _filename_date(path)
        if sidecar_date is not None and name_date is not None and sidecar_date != name_date:
            warnings.append(f"Sidecar save time {sidecar_date.isoformat()} conflicts with filename time "
                            f"{name_date.isoformat()}.")
        date = sidecar_date or name_date
        date_source = "sidecar" if sidecar_date else "filename" if name_date else "unknown"

        stem = path.name
        if stem.lower().endswith(".bin"):
            stem = stem[:-4]
        label_base = stem or path.name
        label_counts[label_base] = label_counts.get(label_base, 0) + 1
        label = (label_base if label_counts[label_base] == 1
                 else f"{label_base} ({label_counts[label_base]})")
        digest = payload_hash[:12]
        snapshot_id = f"snapshot-{ordinal:04d}-{digest}"
        while snapshot_id in used_ids:
            snapshot_id += "-2"
        used_ids.add(snapshot_id)
        snapshots.append({
            "id": snapshot_id,
            "path": display_path,
            "label": label,
            "serial": serial,
            "date": date,
            "dateSource": date_source,
            "warnings": warnings,
            **CalSnapshot(report, payload[10:].hex()).as_record(),
        })
    return snapshots


def ordered_snapshots(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort dated snapshots chronologically, stably, and keep undated entries last."""
    return sorted(snapshots, key=lambda item: (item.get("date") is None,
                                               item.get("date") or datetime.max.replace(tzinfo=timezone.utc)))


def default_reference(snapshots: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Choose the earliest dated snapshot, or the first supplied snapshot."""
    dated = [snapshot for snapshot in snapshots if isinstance(snapshot.get("date"), datetime)]
    return min(dated, key=lambda item: item["date"]) if dated else (snapshots[0] if snapshots else None)


def snapshot_trend(snapshots: list[dict[str, Any]], field_name: str,
                   ref_id: str) -> dict[str, Any]:
    """Return dated coefficient deltas for the reference snapshot's serial group."""
    reference = next((item for item in snapshots if item.get("id") == ref_id), None)
    unavailable = {"available": False, "reason": "", "points": [], "unit": "", "mode": ""}
    if reference is None or not reference.get("comparable") or not isinstance(reference.get("report"), dict):
        unavailable["reason"] = "Reference snapshot has no valid decoded CAL record."
        return unavailable
    allowed = {item["name"]: item["mode"] for item in coefficient_choices({"slots": [reference]})}
    if field_name not in allowed:
        unavailable["reason"] = "The selected field is not an approved scale or divider coefficient."
        return unavailable
    reference_date = reference.get("date")
    if not isinstance(reference_date, datetime):
        unavailable["reason"] = "Reference snapshot has no trusted dated timestamp."
        return unavailable
    if not isinstance(reference.get("serial"), str) or not reference["serial"].strip():
        unavailable["reason"] = "Reference snapshot has no known instrument serial; a serial-specific trend cannot be formed."
        return unavailable
    row = next((item for item in reference["report"].get("schema45", {}).get("values", [])
                if item.get("name") == field_name), None)
    ref_value = _finite_number(row.get("value")) if row else None
    if ref_value is None:
        unavailable["reason"] = "Reference value is missing, invalid, or non-finite."
        return unavailable
    mode = allowed[field_name]
    if mode == "ppm" and ref_value == 0:
        unavailable.update(reason="Relative change is unavailable because the reference value is zero.",
                           unit="ppm", mode=mode)
        return unavailable

    reference_serial = reference.get("serial")
    points = []
    for snapshot in ordered_snapshots(snapshots):
        date = snapshot.get("date")
        if (not snapshot.get("comparable") or not isinstance(snapshot.get("report"), dict)
                or not isinstance(date, datetime) or snapshot.get("serial") != reference_serial):
            continue
        value_row = next((item for item in snapshot["report"].get("schema45", {}).get("values", [])
                          if item.get("name") == field_name), None)
        value = _finite_number(value_row.get("value")) if value_row else None
        if value is None:
            continue
        y = scalar_change(ref_value, value, mode)
        if y is not None:
            points.append({"x": date.timestamp(), "id": snapshot.get("id"), "y": y})
    return {"available": True, "reason": "", "points": points,
            "unit": "ohm" if mode == "ohm_delta" else "ppm", "mode": mode,
            "referenceValue": ref_value}
