"""Byte-exact offline application of `.xs` packages to a complete NOR copy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .offline import (
    APP_BASE,
    APP_END,
    NOR_BASE,
    NOR_END,
    NOR_SIZE,
    REC_BASE,
    REC_END,
    detect_nor_order,
    inspect_nor_bytes,
)
from .srecord import XsPackage


@dataclass(frozen=True)
class NorSimulationResult:
    """Simulation result; the source file is never modified."""

    cpu_before: bytes
    cpu_after: bytes
    report: dict[str, object]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _single_personality(report: dict[str, object]) -> str:
    hits = report["personalityHits"]
    if not isinstance(hits, list) or len(hits) != 1:
        raise ValueError("simulation requires exactly one boot personality writer")
    model = hits[0].get("model")
    if model not in {"34410A", "34411A", "L4411A"}:
        raise ValueError("source NOR boot personality was not recognized")
    return str(model)


def _allowed_window(package: XsPackage) -> tuple[int, int]:
    if package.image_type == "instrumentimage":
        return APP_BASE, APP_END
    if package.image_type == "updateimage":
        return REC_BASE, REC_END
    raise ValueError(f"unsupported image type {package.image_type}")


def _coverage(package: XsPackage) -> dict[str, object]:
    records = package.s3_records
    starts = [int(record.address) for record in records if record.address is not None]
    ends = [start + len(record.data) for start, record in zip(starts, records)]
    gaps = [
        {
            "start": f"0x{previous_end:08X}",
            "endExclusive": f"0x{current_start:08X}",
            "bytes": current_start - previous_end,
        }
        for previous_end, current_start in zip(ends, starts[1:])
        if current_start != previous_end
    ]
    return {
        "firstAddress": f"0x{starts[0]:08X}",
        "endExclusive": f"0x{ends[-1]:08X}",
        "s3Records": len(records),
        "dataBytes": sum(len(record.data) for record in records),
        "gaps": gaps,
    }


def simulate_packages_on_nor(
    raw_nor: bytes,
    packages: list[XsPackage] | tuple[XsPackage, ...],
    *,
    source: str = "<memory>",
) -> NorSimulationResult:
    """Apply packages to a CPU-order NOR copy and validate the resulting images."""

    if not packages:
        raise ValueError("at least one `.xs` package is required")
    cpu, input_order = detect_nor_order(raw_nor)
    if len(cpu) != NOR_SIZE:
        raise AssertionError("detect_nor_order must return exactly 8 MiB")
    output = bytearray(cpu)
    before = inspect_nor_bytes(cpu, source=source)
    current = before
    steps: list[dict[str, object]] = []

    for index, package in enumerate(packages, start=1):
        current_model = _single_personality(current)
        if package.model != current_model:
            raise ValueError(
                f"step {index}: package model {package.model} does not match "
                f"current boot identity {current_model}"
            )
        window_start, window_end = _allowed_window(package)
        changed = 0
        for record in package.s3_records:
            address = record.address
            assert address is not None
            end_exclusive = address + len(record.data)
            if address < window_start or end_exclusive > window_end + 1:
                raise ValueError(
                    f"step {index}: S3 0x{address:08X}..0x{end_exclusive - 1:08X} "
                    f"is outside the {package.image_type} window"
                )
            offset = address - NOR_BASE
            before_record = output[offset : offset + len(record.data)]
            changed += sum(a != b for a, b in zip(before_record, record.data))
            output[offset : offset + len(record.data)] = record.data

        current = inspect_nor_bytes(bytes(output), source=f"{source}:step-{index}")
        object_name = "app" if package.image_type == "instrumentimage" else "recovery"
        image = current[object_name]
        if not isinstance(image, dict) or not image.get("checksumValid"):
            raise ValueError(
                f"step {index}: {object_name} checksum is invalid after package application"
            )
        embedded = current.get("embeddedApp") if object_name == "app" else current.get("embeddedRecovery")
        if object_name == "app" and isinstance(embedded, dict):
            embedded_model = embedded.get("model")
            if embedded_model is not None and embedded_model != package.model:
                raise ValueError(
                    f"step {index}: embedded APP {embedded_model} does not match "
                    f"package model {package.model}"
                )

        mismatch = 0
        for record in package.s3_records:
            address = record.address
            assert address is not None
            offset = address - NOR_BASE
            mismatch += sum(
                a != b
                for a, b in zip(
                    output[offset : offset + len(record.data)], record.data
                )
            )
        if mismatch:
            raise AssertionError("internal simulated read-back error")

        steps.append(
            {
                "index": index,
                "package": str(package.path) if package.path else "<memory>",
                "packageSha256": _sha256(package.raw),
                "modelBefore": current_model,
                "modelAfter": _single_personality(current),
                "imageType": package.image_type,
                "imageRevision": package.headers["imagerev"],
                "coverage": _coverage(package),
                "changedBytes": changed,
                "simulatedReadbackMismatchBytes": mismatch,
                "appChecksumValid": bool(current["app"]["checksumValid"]),
                "recoveryChecksumValid": bool(current["recovery"]["checksumValid"]),
            }
        )

    cpu_after = bytes(output)
    report = {
        "schema": "3441x-nor-update-simulation-v1",
        "source": source,
        "inputBytes": len(raw_nor),
        "usedNorBytes": NOR_SIZE,
        "ignoredTrailingBytes": max(0, len(raw_nor) - NOR_SIZE),
        "inputOrder": input_order,
        "sourceCpuSha256": _sha256(cpu),
        "resultCpuSha256": _sha256(cpu_after),
        "totalChangedBytes": sum(a != b for a, b in zip(cpu, cpu_after)),
        "before": before,
        "steps": steps,
        "after": current,
        "status": "PASS_OFFLINE_MODEL_ONLY",
    }
    return NorSimulationResult(cpu_before=cpu, cpu_after=cpu_after, report=report)
