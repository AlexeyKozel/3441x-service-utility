"""Offline schema45 field explanations; no calibration validity judgement."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


DATA = Path(__file__).with_name("data")


def add_cal_interpretation(report: dict[str, object]) -> None:
    """Enrich a freshly decoded report with exact field bindings and shared cards."""
    if report["version"] != 45 or report["bodyLength"] != 4924:
        report["interpretation"] = {
            "status": "unavailable",
            "reason": "Explanations require CAL version 45 and a 4924-byte body.",
        }
        return
    bindings = json.loads((DATA / "cal_bindings_v1.json").read_text(encoding="utf-8"))
    meanings = json.loads((DATA / "cal_meanings_v1.json").read_text(encoding="utf-8"))
    registry_hash = hashlib.sha256((DATA / "schema45_registry_snapshot.json").read_bytes()).hexdigest()
    if (bindings.get("schema") != "cal_bindings.v1" or bindings.get("registrySha256") != registry_hash
            or meanings.get("schema") != "cal_meanings.v1"):
        raise ValueError("CAL interpretation catalog does not match the schema45 registry")
    rows = bindings["rows"]
    families = meanings["families"]
    decoded = report["schema45"]
    values = decoded["values"]
    if len(rows) != 1072 or len(values) != len(rows) or {row["family"] for row in rows} != set(families):
        raise ValueError("CAL interpretation catalog has incomplete field coverage")
    # Validate the complete join before annotating any field. No prefix guessing.
    end = 0
    for value, row in zip(values, rows):
        width = {"double": 8, "int32": 4}.get(row["type"])
        if (any(value[key] != row[key] for key in ("offset", "name", "type"))
                or row["offset"] != end or row["width"] != width):
            raise ValueError("CAL interpretation field identity mismatch")
        if families[row["family"]]["usage_status"] not in {"established", "partial", "open"}:
            raise ValueError("CAL interpretation catalog has an invalid usage status")
        end += width
    if end != 4924:
        raise ValueError("CAL interpretation catalog has an invalid body span")
    for value, row in zip(values, rows):
        value["meaning"] = {key: row[key] for key in
                            ("family", "nameBase", "groupId", "elementIndex", "displaySuffix")}
    decoded["meanings"] = families
    report["interpretation"] = {
        "status": "available",
        "catalogSchema": meanings["schema"],
        "scope": meanings["scope"],
        "bindingScope": bindings["bindingScope"],
        "payloadIntegrity": "checksum_valid" if report["checksumValid"] else "checksum_mismatch",
        "valueAssessment": "not_performed",
        "note": "Usage status describes evidence for field meaning, not whether its value is correct."
                " Explanations do not establish the active instrument configuration.",
    }
