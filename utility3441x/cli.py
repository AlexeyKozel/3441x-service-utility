"""English command-line interface for 3441x Service Utility."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from . import (
    LIVE_APP_IMAGE_WRITE_ENABLED,
    LIVE_IDENTITY_WRITE_ENABLED,
    __version__,
)
from .app_update import wait_for_final_app_identity
from .backup import create_service_backup, verify_service_backup
from .flash_model import simulate_packages_on_nor
from .identity import (
    REC_BASE,
    SA96_SIZE,
    assert_fresh_readback_before_write,
    build_sa96_identity_write_plan,
    complete_identity_switch_after_end,
    default_backup_root,
)
from .instrument import VisaInstrument, dump_nor
from .offline import inspect_nor_file, parse_cal_payload
from .srecord import (
    assert_app_image_package,
    assert_app_upload_preflight,
    load_xs,
)
from .update_protocol import dry_run_transcript, execute_emulated, execute_update


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str))


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )


def _package_report(path: Path) -> tuple[object, dict[str, object]]:
    package = load_xs(path)
    report = {
        "file": str(path),
        "sha256": hashlib.sha256(package.raw).hexdigest(),
        "headers": package.headers,
        "selector": package.selector,
        "payloadBytes": len(package.payload),
        "recordCount": len(package.records),
        "s3RecordCount": len(package.s3_records),
        "addressFirst": f"0x{package.s3_records[0].address:08X}",
        "addressLast": f"0x{package.s3_records[-1].address:08X}",
    }
    return package, report


def _empty_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise ValueError(f"Folder must be empty: {path}")


def _identity_backup_folder(serial: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = default_backup_root()
    folder = root / f"{serial}_identity_{stamp}"
    suffix = 1
    while folder.exists():
        folder = root / f"{serial}_identity_{stamp}_{suffix}"
        suffix += 1
    return folder


class CliProgress:
    def __init__(self, label: str):
        self.label = label
        self.started = time.monotonic()
        self.last_emit = 0.0

    @staticmethod
    def _bytes(value: float) -> str:
        size = float(value)
        for unit in ("B", "KiB", "MiB", "GiB"):
            if abs(size) < 1024 or unit == "GiB":
                return f"{size:.1f} {unit}"
            size /= 1024
        raise AssertionError

    def __call__(self, completed: int, total: int) -> None:
        now = time.monotonic()
        if completed < total and now - self.last_emit < 0.10:
            return
        self.last_emit = now
        elapsed = max(now - self.started, 1e-6)
        rate = completed / elapsed
        eta = (total - completed) / rate if rate > 0 else None
        if eta is None:
            eta_text = "--:--"
        else:
            eta_seconds = int(round(eta))
            hours, remainder = divmod(eta_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            eta_text = (
                f"{hours:d}:{minutes:02d}:{seconds:02d}"
                if hours
                else f"{minutes:02d}:{seconds:02d}"
            )
        percent = completed * 100 / max(1, total)
        print(
            f"\r{self.label}: {percent:5.1f}% | {self._bytes(rate)}/s | ETA {eta_text}",
            end="\n" if completed >= total else "",
            file=sys.stderr,
            flush=True,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="3441x Service Utility")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_nor = sub.add_parser("inspect-nor", help="Inspect a complete NOR dump")
    inspect_nor.add_argument("image", type=Path)

    inspect_cal = sub.add_parser("inspect-cal", help="Inspect a CAL:DATA:ALL payload")
    inspect_cal.add_argument("payload", type=Path)

    inspect_xs = sub.add_parser("inspect-xs", help="Validate an .xs/S-record package")
    inspect_xs.add_argument("package", type=Path)

    dry = sub.add_parser("dry-run-update", help="Generate a safe update transcript")
    dry.add_argument("package", type=Path)
    dry.add_argument("--block-size", type=int, default=65536)

    emulate = sub.add_parser("emulate-update", help="Run the byte-exact updater emulator")
    emulate.add_argument("package", type=Path)
    emulate.add_argument("--block-size", type=int, default=65536)

    simulate = sub.add_parser(
        "simulate-nor-update",
        help="Apply one or more .xs packages to an in-memory NOR copy",
    )
    simulate.add_argument("nor", type=Path)
    simulate.add_argument("packages", nargs="+", type=Path)
    simulate.add_argument(
        "--output-cpu",
        type=Path,
        help="Optionally save the result as an exact 8 MiB CPU-order dump",
    )
    simulate.add_argument("--report", type=Path)

    diagnostics = sub.add_parser("diagnostics", help="Read supported diagnostics")
    diagnostics.add_argument("--resource", required=True)

    backup_cal = sub.add_parser("backup-cal", help="Read and save CAL")
    backup_cal.add_argument("--resource", required=True)
    backup_cal.add_argument("--output", required=True, type=Path)

    nor_dump = sub.add_parser("dump-nor", help="Read the complete NOR with resume support")
    nor_dump.add_argument("--resource", required=True)
    nor_dump.add_argument("--output", required=True, type=Path)
    nor_dump.add_argument("--no-resume", action="store_true")

    backup = sub.add_parser("service-backup", help="Create a verified service backup")
    backup.add_argument("--resource", required=True)
    backup.add_argument("--folder", required=True, type=Path)
    backup.add_argument("--include-nor", action="store_true")

    verify = sub.add_parser("verify-backup", help="Verify a service backup")
    verify.add_argument("folder", type=Path)

    verify_sa96 = sub.add_parser(
        "verify-sa96",
        help="Read current SA96 and compare it with a saved original sector",
    )
    verify_sa96.add_argument("backup", type=Path)
    verify_sa96.add_argument("--resource", required=True)
    verify_sa96.add_argument("--output", type=Path)

    upload = sub.add_parser("firmware-upload", help="Upload a supported .xs package")
    upload.add_argument("package", type=Path)
    upload.add_argument("--resource", required=True)
    upload.add_argument("--execute", action="store_true")
    upload.add_argument(
        "--yes",
        action="store_true",
        help="Confirm APP image upload",
    )
    upload.add_argument("--log", type=Path)

    switch = sub.add_parser(
        "identity-switch",
        help="Switch 34410A/34411A using the native SA96 from this session",
    )
    switch.add_argument("--resource", required=True)
    switch.add_argument("--to", required=True, choices=("34410A", "34411A"))
    switch.add_argument(
        "--backup-folder",
        type=Path,
        help="Optional folder; otherwise it is created beside the utility",
    )
    switch.add_argument(
        "--full-backup",
        action="store_true",
        help="Additionally create a complete service backup before writing (slow)",
    )
    switch.add_argument("--execute", action="store_true")
    switch.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the identity write after reviewing the saved hash-bound plan",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inspect-nor":
        _print_json(inspect_nor_file(args.image))
        return 0
    if args.command == "inspect-cal":
        _print_json(parse_cal_payload(args.payload.read_bytes()))
        return 0
    if args.command == "inspect-xs":
        _, report = _package_report(args.package)
        _print_json(report)
        return 0
    if args.command in {"dry-run-update", "emulate-update"}:
        package, report = _package_report(args.package)
        if args.command == "dry-run-update":
            report["transcript"] = dry_run_transcript(package, args.block_size)
        else:
            emulator = execute_emulated(package, args.block_size)
            report["emulatorEvents"] = emulator.events
            report["emulatorStatus"] = "PASS"
        _print_json(report)
        return 0
    if args.command == "simulate-nor-update":
        packages = [load_xs(path) for path in args.packages]
        result = simulate_packages_on_nor(args.nor.read_bytes(), packages, source=str(args.nor))
        if args.output_cpu:
            args.output_cpu.write_bytes(result.cpu_after)
        if args.report:
            _write_json(args.report, result.report)
        _print_json(result.report)
        return 0
    if args.command == "verify-backup":
        _print_json(verify_service_backup(args.folder))
        return 0
    if args.command == "verify-sa96":
        original = args.backup.read_bytes()
        if len(original) != SA96_SIZE:
            raise ValueError(
                f"Saved SA96 must be exactly {SA96_SIZE} bytes, got {len(original)}"
            )
        with VisaInstrument(args.resource, timeout_ms=30_000) as instrument:
            identity = instrument.identity()
            current = instrument.read_memory(
                REC_BASE,
                SA96_SIZE,
                batch_words=64,
                progress=CliProgress("Reading current SA96 for comparison"),
            )
        output = args.output or args.backup.with_name(
            f"sa96_current_verify_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
        )
        output.write_bytes(current)
        differences = [
            index
            for index, (before, after) in enumerate(zip(original, current))
            if before != after
        ]
        report = {
            "status": "IDENTICAL" if not differences else "DIFFERENT",
            "identity": identity,
            "originalFile": str(args.backup),
            "currentFile": str(output),
            "originalSha256": hashlib.sha256(original).hexdigest(),
            "currentSha256": hashlib.sha256(current).hexdigest(),
            "differenceCount": len(differences),
            "firstDifferenceOffsets": [f"0x{offset:04X}" for offset in differences[:64]],
        }
        _write_json(output.with_suffix(output.suffix + ".json"), report)
        _print_json(report)
        return 0

    if args.command == "diagnostics":
        with VisaInstrument(args.resource) as instrument:
            _print_json(instrument.diagnostics())
        return 0
    if args.command == "backup-cal":
        with VisaInstrument(args.resource) as instrument:
            payload, report = instrument.read_calibration()
            args.output.write_bytes(payload)
            _write_json(args.output.with_suffix(args.output.suffix + ".json"), report)
            _print_json(report)
        return 0
    if args.command == "dump-nor":
        with VisaInstrument(args.resource) as instrument:
            dump_nor(
                instrument,
                args.output,
                resume=not args.no_resume,
                progress=CliProgress("Reading NOR"),
            )
        _print_json(inspect_nor_file(args.output))
        return 0
    if args.command == "service-backup":
        with VisaInstrument(args.resource) as instrument:
            result = create_service_backup(
                instrument,
                args.folder,
                include_nor=args.include_nor,
                progress=CliProgress("Reading NOR"),
            )
        _print_json(result)
        return 0
    if args.command == "firmware-upload":
        package, package_report = _package_report(args.package)
        if not args.execute:
            package_report["status"] = "DRY_RUN_ONLY"
            package_report["transcript"] = dry_run_transcript(package, 65536)
            _print_json(package_report)
            return 0
        assert_app_image_package(package)
        if not LIVE_APP_IMAGE_WRITE_ENABLED:
            raise PermissionError(
                "APP image upload is disabled in this build"
            )
        with VisaInstrument(args.resource, timeout_ms=30_000) as instrument:
            before = instrument.identity()
            assert_app_upload_preflight(package, before)
            if not args.yes:
                raise PermissionError(
                    "APP image upload is blocked. Pass --yes to confirm"
                )
            result = execute_update(
                instrument,
                package,
                destructive_authorized=True,
                progress=CliProgress("Uploading firmware"),
            )
            print(
                "APP image was accepted. Power-cycle the instrument now; "
                "waiting for its final boot...",
                file=sys.stderr,
            )
            after = wait_for_final_app_identity(
                instrument,
                package,
                before,
                status=lambda message: print(message, file=sys.stderr),
            )
        log = {
            "package": package_report,
            "identityBefore": before,
            "identityAfter": after,
            "result": result,
        }
        if args.log:
            _write_json(args.log, log)
        _print_json(log)
        return 0
    if args.command == "identity-switch":
        if args.execute and not LIVE_IDENTITY_WRITE_ENABLED:
            raise PermissionError(
                "Live identity writes are disabled in this build"
            )
        with VisaInstrument(args.resource, timeout_ms=30_000) as instrument:
            snapshot = instrument.collect_sa96_snapshot(
                progress=CliProgress("Reading native SA96")
            )
            plan = build_sa96_identity_write_plan(snapshot, args.to)
            folder = args.backup_folder or _identity_backup_folder(snapshot.serial)
            _empty_folder(folder)
            (folder / "sa96_original_cpu.bin").write_bytes(plan.source_sa96)
            target_package = folder / "identity_switch_native_sa96.xs"
            target_package.write_bytes(plan.package_bytes)
            _write_json(folder / "identity_write_plan.json", plan.as_dict())
            if args.full_backup:
                create_service_backup(
                    instrument,
                    folder / "full_service_backup",
                    include_nor=True,
                    progress=CliProgress("Creating full backup: reading NOR"),
                )
            if not args.execute:
                result = plan.as_dict()
                result["status"] = "PLAN_ONLY_NO_WRITE"
                result["backupFolder"] = str(folder)
                _print_json(result)
                return 0
            if not args.yes:
                raise PermissionError(
                    "Identity switch is blocked. Review the saved write plan and pass --yes"
                )
            identity_now = instrument.identity()
            if identity_now["serial"] != snapshot.serial or identity_now["model"] != snapshot.current_model:
                raise RuntimeError("Instrument identity changed after preflight")
            current_sector = instrument.read_memory(
                0xFFE00000,
                0x10000,
                batch_words=64,
                progress=CliProgress("Re-reading SA96 before write"),
            )
            assert_fresh_readback_before_write(plan, current_sector)
            package = load_xs(target_package)
            update_result = execute_update(
                instrument,
                package,
                destructive_authorized=True,
                reboot_updateimage=False,
                progress=CliProgress("Uploading patched SA96"),
            )
            completion = complete_identity_switch_after_end(
                instrument,
                plan,
                progress=CliProgress("Verifying programmed SA96"),
                status=lambda message: print(message, file=sys.stderr),
            )
            result = {
                "status": "COMPLETED_AND_READBACK_VERIFIED",
                "backupFolder": str(folder),
                "fullServiceBackupCreated": bool(args.full_backup),
                "plan": plan.as_dict(),
                "update": update_result,
                **completion,
            }
            _write_json(folder / "identity_switch_result.json", result)
            _print_json(result)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
