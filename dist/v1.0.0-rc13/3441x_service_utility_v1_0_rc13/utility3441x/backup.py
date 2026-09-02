"""Create and verify service backups using supported read-only APIs."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .instrument import VisaInstrument, dump_nor
from .offline import inspect_nor_file, parse_cal_payload


MANIFEST_SCHEMA = "3441x-service-backup-v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def create_service_backup(
    instrument: VisaInstrument,
    folder: Path,
    *,
    include_nor: bool,
    progress=None,
) -> dict[str, object]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise ValueError("service backup folder must be empty")

    identity = instrument.identity()
    diagnostics = instrument.diagnostics()
    calibration, calibration_report = instrument.read_calibration()
    files: list[dict[str, object]] = []

    def register(path: Path, role: str) -> None:
        files.append(
            {
                "name": path.name,
                "role": role,
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )

    identity_path = folder / "identity.json"
    _write_json(identity_path, identity)
    register(identity_path, "instrument identity from *IDN?")

    diagnostics_path = folder / "diagnostics.json"
    _write_json(diagnostics_path, diagnostics)
    register(diagnostics_path, "read-only diagnostic snapshot")

    calibration_path = folder / "calibration_current.bin"
    calibration_path.write_bytes(calibration)
    register(calibration_path, "current CAL:DATA:ALL logical object")
    calibration_json = folder / "calibration_current.json"
    _write_json(calibration_json, calibration_report)
    register(calibration_json, "decoded CAL metadata and schema45 values")

    if include_nor:
        nor_path = folder / "main_flash_cpu.bin"
        dump_nor(instrument, nor_path, resume=False, progress=progress)
        nor_report = inspect_nor_file(nor_path)
        nor_json = folder / "main_flash_report.json"
        _write_json(nor_json, nor_report)
        register(nor_path, "full 8 MiB NOR in CPU byte order")
        register(nor_json, "NOR integrity and firmware analysis")

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "resource": instrument.resource,
        "sessionId": instrument.session_id,
        "identity": identity,
        "scope": "supported read-only instrument interfaces",
        "files": files,
    }
    manifest_path = folder / "manifest.json"
    _write_json(manifest_path, manifest)
    with manifest_path.open("rb") as stream:
        os.fsync(stream.fileno())
    return verify_service_backup(folder)


def verify_service_backup(folder: Path) -> dict[str, object]:
    folder = Path(folder)
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("manifest.json was not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unsupported service backup schema")
    results = []
    for entry in manifest.get("files", []):
        name = entry.get("name")
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("manifest contains an unsafe file name")
        path = folder / name
        actual = _sha256_file(path) if path.is_file() else None
        results.append(
            {
                "name": name,
                "exists": path.is_file(),
                "expectedSha256": entry.get("sha256"),
                "actualSha256": actual,
                "hashValid": actual is not None and actual == entry.get("sha256"),
            }
        )
    analysis: dict[str, object] = {}
    calibration = folder / "calibration_current.bin"
    if calibration.is_file():
        analysis["calibration"] = parse_cal_payload(calibration.read_bytes())
    nor = folder / "main_flash_cpu.bin"
    if nor.is_file():
        analysis["nor"] = inspect_nor_file(nor)
    return {
        "folder": str(folder),
        "manifest": manifest,
        "files": results,
        "allHashesValid": bool(results) and all(item["hashValid"] for item in results),
        "analysis": analysis,
    }
