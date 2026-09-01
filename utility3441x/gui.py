"""English Tk front end for the verified service-utility core."""

from __future__ import annotations

import hashlib
import json
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from . import (
    LIVE_APP_IMAGE_WRITE_ENABLED,
    LIVE_IDENTITY_WRITE_ENABLED,
)
from .app_update import wait_for_final_app_identity
from .backup import create_service_backup
from .identity import (
    REC_BASE,
    SA96_SIZE,
    assert_fresh_readback_before_write,
    build_sa96_identity_write_plan,
    complete_identity_switch_after_end,
    default_backup_root,
)
from .instrument import VisaInstrument, dump_nor
from .srecord import (
    assert_app_image_package,
    assert_app_upload_preflight,
    load_xs,
)
from .update_protocol import execute_update


def _format_bytes(value: float) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    size = float(value)
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError


def _format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "--:--"
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


class ServiceUtilityGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("3441x Service Utility 1.0 RC11 Hardware Validation")
        self.geometry("1050x760")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cli = Path(__file__).resolve().parents[1] / "3441x_service_utility.py"
        self.resource = tk.StringVar(value="TCPIP0::192.168.0.10::inst0::INSTR")
        self.package = tk.StringVar()
        self.target_model = tk.StringVar(value="34411A")
        self.full_identity_backup = tk.BooleanVar(value=False)
        self.progress_title = tk.StringVar(value="Ready")
        self.progress_stats = tk.StringVar(value="")
        self._busy = False
        self._build()
        self.after(100, self._drain)

    def _build(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="VISA resource:").pack(side="left")
        ttk.Entry(top, textvariable=self.resource, width=55).pack(side="left", padx=6)
        ttk.Button(top, text="Diagnostics", command=self._diagnostics).pack(side="left")

        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        offline = ttk.Frame(tabs, padding=8)
        backup = ttk.Frame(tabs, padding=8)
        firmware = ttk.Frame(tabs, padding=8)
        identity = ttk.Frame(tabs, padding=8)
        tabs.add(offline, text="Offline analysis")
        tabs.add(backup, text="Backup")
        tabs.add(firmware, text="Firmware")
        tabs.add(identity, text="Boot identity")

        ttk.Button(offline, text="Inspect NOR dump…", command=self._inspect_nor).pack(anchor="w", pady=3)
        ttk.Button(offline, text="Inspect CAL payload…", command=self._inspect_cal).pack(anchor="w", pady=3)
        ttk.Button(offline, text="Inspect .xs package…", command=self._inspect_xs).pack(anchor="w", pady=3)
        ttk.Button(
            offline,
            text="Simulate selected .xs on a NOR copy…",
            command=self._simulate_nor,
        ).pack(anchor="w", pady=3)

        ttk.Label(
            backup,
            text="These operations use supported read-only instrument requests.",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Button(backup, text="Save CAL…", command=self._backup_cal).pack(anchor="w", pady=3)
        ttk.Button(backup, text="Read complete NOR…", command=self._dump_nor).pack(anchor="w", pady=3)
        ttk.Button(backup, text="Create service backup…", command=self._service_backup).pack(anchor="w", pady=3)

        package_row = ttk.Frame(firmware)
        package_row.pack(fill="x")
        ttk.Entry(package_row, textvariable=self.package).pack(side="left", fill="x", expand=True)
        ttk.Button(package_row, text="Select .xs…", command=self._choose_package).pack(side="left", padx=6)
        ttk.Button(firmware, text="Dry-run transcript", command=self._dry_run).pack(anchor="w", pady=8)
        ttk.Button(
            firmware,
            text="Upload original APP image to instrument",
            command=self._upload,
            state="normal" if LIVE_APP_IMAGE_WRITE_ENABLED else "disabled",
        ).pack(anchor="w", pady=3)
        ttk.Label(
            firmware,
            text=(
                "Only validated 34410A/34411A instrumentimage APP packages are "
                "accepted. Cross-loading between these two models is allowed. "
                "Recovery updateimage remains blocked; a Yes/No confirmation is required."
            ),
            wraplength=900,
        ).pack(anchor="w", pady=8)

        ttk.Label(
            identity,
            text=(
                "The utility reads only the native 64 KiB SA96 sector, saves it "
                "automatically, patches the boot identity, uploads it, and performs "
                "a complete read-back before reboot."
            ),
            wraplength=900,
        ).pack(anchor="w", pady=(0, 10))
        target_row = ttk.Frame(identity)
        target_row.pack(anchor="w")
        ttk.Label(target_row, text="Target identity:").pack(side="left", padx=(0, 8))
        ttk.Combobox(
            target_row,
            textvariable=self.target_model,
            values=("34410A", "34411A"),
            state="readonly",
            width=12,
        ).pack(side="left")
        ttk.Checkbutton(
            identity,
            text="Create an additional full service backup first (slow)",
            variable=self.full_identity_backup,
        ).pack(anchor="w", pady=(12, 3))
        ttk.Label(
            identity,
            text="The original SA96 backup is always created, even when this box is clear.",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            identity,
            text=(
                "RC11 hardware-validation mode: identity writing and APP upload are "
                "enabled, while general Recovery upload remains blocked. Review the "
                "hash-bound plan in the Yes/No confirmation before proceeding."
            ),
            wraplength=900,
        ).pack(anchor="w", pady=(4, 6))
        ttk.Button(
            identity,
            text="Verify current SA96 against saved backup…",
            command=self._verify_sa96_backup,
        ).pack(anchor="w", pady=4)
        ttk.Button(
            identity,
            text="Switch identity",
            command=self._identity_execute,
            state="normal" if LIVE_IDENTITY_WRITE_ENABLED else "disabled",
        ).pack(anchor="w", pady=4)

        progress_frame = ttk.LabelFrame(self, text="Progress", padding=8)
        progress_frame.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(progress_frame, textvariable=self.progress_title).pack(anchor="w")
        self.progress = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=4)
        ttk.Label(progress_frame, textvariable=self.progress_stats).pack(anchor="w")

        output_frame = ttk.Frame(self)
        output_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)

        self.output = tk.Text(output_frame, wrap="none", height=14)
        output_scroll_y = ttk.Scrollbar(
            output_frame, orient="vertical", command=self.output.yview
        )
        output_scroll_x = ttk.Scrollbar(
            output_frame, orient="horizontal", command=self.output.xview
        )
        self.output.configure(
            yscrollcommand=output_scroll_y.set,
            xscrollcommand=output_scroll_x.set,
        )
        self.output.grid(row=0, column=0, sticky="nsew")
        output_scroll_y.grid(row=0, column=1, sticky="ns")
        output_scroll_x.grid(row=1, column=0, sticky="ew")

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "output":
                    self.output.insert("end", str(payload) + "\n")
                    self.output.see("end")
                elif kind == "error":
                    self.output.insert("end", "ERROR: " + str(payload) + "\n")
                    self.output.see("end")
                    messagebox.showerror("3441x Service Utility", str(payload))
                elif kind == "indeterminate":
                    self.progress.stop()
                    self.progress.configure(mode="indeterminate", maximum=100)
                    self.progress.start(12)
                    self.progress_title.set(str(payload))
                    self.progress_stats.set("Working…")
                elif kind == "progress":
                    item = dict(payload)
                    self.progress.stop()
                    self.progress.configure(mode="determinate", maximum=max(1, item["total"]))
                    self.progress["value"] = item["completed"]
                    self.progress_title.set(item["label"])
                    percent = item["completed"] * 100 / max(1, item["total"])
                    self.progress_stats.set(
                        f"{percent:5.1f}%  ·  {_format_bytes(item['rate'])}/s  ·  "
                        f"ETA {_format_eta(item['eta'])}"
                    )
                elif kind == "confirm_yes_no":
                    item = dict(payload)
                    item["answer"]["value"] = messagebox.askyesno(
                        item["title"], item["message"]
                    )
                    item["event"].set()
                elif kind == "show_info":
                    item = dict(payload)
                    messagebox.showinfo(item["title"], item["message"])
                    item["event"].set()
                elif kind == "done":
                    item = dict(payload)
                    self.progress.stop()
                    self.progress.configure(mode="determinate", maximum=100)
                    self.progress["value"] = 100 if item["success"] else 0
                    self.progress_title.set(item["label"])
                    self.progress_stats.set("Completed" if item["success"] else "Failed")
                    self._busy = False
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _progress_callback(self, label: str) -> Callable[[int, int], None]:
        started = time.monotonic()
        last_emit = [0.0]

        def report(completed: int, total: int) -> None:
            now = time.monotonic()
            if completed < total and now - last_emit[0] < 0.10:
                return
            last_emit[0] = now
            elapsed = max(now - started, 1e-6)
            rate = completed / elapsed
            eta = (total - completed) / rate if rate > 0 else None
            self.events.put(
                (
                    "progress",
                    {
                        "label": label,
                        "completed": completed,
                        "total": total,
                        "rate": rate,
                        "eta": eta,
                    },
                )
            )

        return report

    def _run_worker(self, label: str, function: Callable[[], object]) -> None:
        if self._busy:
            messagebox.showwarning("3441x Service Utility", "Another operation is still running.")
            return
        self._busy = True
        self.events.put(("indeterminate", label))

        def worker() -> None:
            try:
                result = function()
                if result is not None:
                    self.events.put(("output", json.dumps(result, ensure_ascii=False, indent=2, default=str)))
                self.events.put(("done", {"label": label, "success": True}))
            except Exception as exc:
                self.events.put(("error", str(exc)))
                self.events.put(("done", {"label": "Operation failed", "success": False}))

        threading.Thread(target=worker, daemon=True).start()

    def _confirm_yes_no_from_worker(self, title: str, message: str) -> bool:
        event = threading.Event()
        answer: dict[str, bool | None] = {"value": None}
        self.events.put(
            (
                "confirm_yes_no",
                {"title": title, "message": message, "event": event, "answer": answer},
            )
        )
        event.wait()
        return answer["value"] is True

    def _show_info_from_worker(self, title: str, message: str) -> None:
        event = threading.Event()
        self.events.put(
            (
                "show_info",
                {"title": title, "message": message, "event": event},
            )
        )
        event.wait()

    def _run_cli(self, arguments: list[str]) -> None:
        def operation() -> object:
            completed = subprocess.run(
                [sys.executable, str(self.cli), *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode:
                raise RuntimeError(completed.stderr.rstrip() or f"Exit code {completed.returncode}")
            return completed.stdout.rstrip()

        self._run_worker("Running offline command", operation)

    def _diagnostics(self) -> None:
        resource = self.resource.get()

        def operation() -> object:
            with VisaInstrument(resource) as instrument:
                return instrument.diagnostics()

        self._run_worker("Reading diagnostics", operation)

    def _file_command(self, title: str, command: str) -> None:
        path = filedialog.askopenfilename(title=title)
        if path:
            self._run_cli([command, path])

    def _inspect_nor(self) -> None:
        self._file_command("Select a complete NOR dump", "inspect-nor")

    def _inspect_cal(self) -> None:
        self._file_command("Select a CAL payload", "inspect-cal")

    def _inspect_xs(self) -> None:
        self._file_command("Select an .xs package", "inspect-xs")

    def _simulate_nor(self) -> None:
        if not self.package.get():
            self._choose_package()
        if not self.package.get():
            return
        nor = filedialog.askopenfilename(title="Select a complete NOR dump")
        if nor:
            self._run_cli(["simulate-nor-update", nor, self.package.get()])

    def _backup_cal(self) -> None:
        path = filedialog.asksaveasfilename(title="Save CAL", defaultextension=".bin")
        if not path:
            return
        resource = self.resource.get()

        def operation() -> object:
            with VisaInstrument(resource) as instrument:
                payload, report = instrument.read_calibration()
            Path(path).write_bytes(payload)
            Path(path + ".json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            return report

        self._run_worker("Reading CAL", operation)

    def _dump_nor(self) -> None:
        path = filedialog.asksaveasfilename(title="Save complete NOR", defaultextension=".bin")
        if not path:
            return
        resource = self.resource.get()

        def operation() -> object:
            progress = self._progress_callback("Reading complete NOR")
            with VisaInstrument(resource) as instrument:
                dump_nor(instrument, Path(path), resume=True, progress=progress)
            return {"status": "completed", "file": path}

        self._run_worker("Opening instrument for NOR backup", operation)

    def _service_backup(self) -> None:
        folder = filedialog.askdirectory(title="Select an empty backup folder")
        if not folder:
            return
        include_nor = messagebox.askyesno("Service backup", "Include the complete 8 MiB NOR dump?")
        resource = self.resource.get()

        def operation() -> object:
            progress = self._progress_callback("Creating service backup: reading NOR")
            with VisaInstrument(resource) as instrument:
                return create_service_backup(
                    instrument,
                    Path(folder),
                    include_nor=include_nor,
                    progress=progress,
                )

        self._run_worker("Creating service backup", operation)

    def _choose_package(self) -> None:
        path = filedialog.askopenfilename(
            title="Select an .xs package",
            filetypes=(("XS package", "*.xs"), ("All files", "*.*")),
        )
        if path:
            self.package.set(path)

    def _dry_run(self) -> None:
        if not self.package.get():
            self._choose_package()
        if self.package.get():
            self._run_cli(["dry-run-update", self.package.get()])

    def _upload(self) -> None:
        if not self.package.get():
            self._choose_package()
        if not self.package.get():
            return
        package_path = Path(self.package.get())
        resource = self.resource.get()

        def operation() -> object:
            package = load_xs(package_path)
            assert_app_image_package(package)
            with VisaInstrument(resource, timeout_ms=30_000) as instrument:
                before = instrument.identity()
                assert_app_upload_preflight(package, before)
                if not self._confirm_yes_no_from_worker(
                    "Confirm APP upload",
                    "Are you sure you want to upload this APP image?",
                ):
                    raise PermissionError("APP upload cancelled")
                result = execute_update(
                    instrument,
                    package,
                    destructive_authorized=True,
                    progress=self._progress_callback("Uploading firmware"),
                )
                self._show_info_from_worker(
                    "Completing APP update",
                    "The APP image was accepted.\n\n"
                    "Power-cycle the instrument, wait until it has booted, "
                    "then click OK.",
                )
                after = wait_for_final_app_identity(
                    instrument,
                    package,
                    before,
                    status=lambda message: self.events.put(("indeterminate", message)),
                )
            return {"identityBefore": before, "identityAfter": after, "result": result}

        self._run_worker("Preparing firmware upload", operation)

    @staticmethod
    def _identity_backup_folder(serial: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = default_backup_root()
        folder = root / f"{serial}_identity_{stamp}"
        suffix = 1
        while folder.exists():
            folder = root / f"{serial}_identity_{stamp}_{suffix}"
            suffix += 1
        folder.mkdir(parents=True)
        return folder

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def _verify_sa96_backup(self) -> None:
        backup_name = filedialog.askopenfilename(
            title="Select the saved original SA96",
            filetypes=(("SA96 binary", "*.bin"), ("All files", "*.*")),
        )
        if not backup_name:
            return
        backup_path = Path(backup_name)
        resource = self.resource.get()

        def operation() -> object:
            original = backup_path.read_bytes()
            if len(original) != SA96_SIZE:
                raise ValueError(
                    f"Saved SA96 must be exactly {SA96_SIZE} bytes, got {len(original)}"
                )
            with VisaInstrument(resource, timeout_ms=30_000) as instrument:
                identity = instrument.identity()
                current = instrument.read_memory(
                    REC_BASE,
                    SA96_SIZE,
                    batch_words=64,
                    progress=self._progress_callback("Reading current SA96 for comparison"),
                )
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            current_path = backup_path.with_name(f"sa96_current_verify_{stamp}.bin")
            report_path = backup_path.with_name(f"sa96_comparison_{stamp}.json")
            current_path.write_bytes(current)
            differences = [
                index
                for index, (before, after) in enumerate(zip(original, current))
                if before != after
            ]
            report = {
                "status": "IDENTICAL" if not differences else "DIFFERENT",
                "identity": identity,
                "originalFile": str(backup_path),
                "currentFile": str(current_path),
                "originalSha256": hashlib.sha256(original).hexdigest(),
                "currentSha256": hashlib.sha256(current).hexdigest(),
                "differenceCount": len(differences),
                "firstDifferenceOffsets": [
                    f"0x{offset:04X}" for offset in differences[:64]
                ],
            }
            self._write_json(report_path, report)
            report["reportFile"] = str(report_path)
            return report

        self._run_worker("Verifying current SA96 against saved backup", operation)

    def _identity_execute(self) -> None:
        if not LIVE_IDENTITY_WRITE_ENABLED:
            messagebox.showerror(
                "3441x Service Utility",
                "Live identity writing is disabled in this build.",
            )
            return
        target = self.target_model.get()
        full_backup = self.full_identity_backup.get()
        resource = self.resource.get()

        def operation() -> object:
            with VisaInstrument(resource, timeout_ms=30_000) as instrument:
                snapshot = instrument.collect_sa96_snapshot(
                    progress=self._progress_callback("Reading native SA96")
                )
                plan = build_sa96_identity_write_plan(snapshot, target)
                folder = self._identity_backup_folder(snapshot.serial)
                (folder / "sa96_original_cpu.bin").write_bytes(plan.source_sa96)
                (folder / "identity_switch_native_sa96.xs").write_bytes(plan.package_bytes)
                self._write_json(folder / "identity_write_plan.json", plan.as_dict())
                self.events.put(("output", f"Original SA96 saved to: {folder}"))

                if full_backup:
                    create_service_backup(
                        instrument,
                        folder / "full_service_backup",
                        include_nor=True,
                        progress=self._progress_callback("Creating full backup: reading NOR"),
                    )

                plan_report = plan.as_dict()
                confirmation = (
                    f"Instrument: {snapshot.serial}\n"
                    f"Identity: {snapshot.current_model} -> {target}\n"
                    f"Source SA96 SHA-256: {plan_report['sourceSa96Sha256']}\n"
                    f"Target SA96 SHA-256: {plan_report['targetSa96Sha256']}\n"
                    f"XS SHA-256: {plan_report['packageSha256']}\n\n"
                    f"Original SA96 and the write plan were saved to:\n{folder}\n\n"
                    "Proceed with one write attempt?"
                )
                if not self._confirm_yes_no_from_worker(
                    "Confirm identity switch", confirmation
                ):
                    raise PermissionError(
                        f"Identity switch cancelled. Original SA96 was saved to {folder}"
                    )
                identity_now = instrument.identity()
                if identity_now["serial"] != snapshot.serial or identity_now["model"] != snapshot.current_model:
                    raise RuntimeError("Instrument identity changed after preflight")
                current_sector = instrument.read_memory(
                    0xFFE00000,
                    0x10000,
                    batch_words=64,
                    progress=self._progress_callback("Re-reading SA96 before write"),
                )
                assert_fresh_readback_before_write(plan, current_sector)
                package = load_xs(folder / "identity_switch_native_sa96.xs")
                update_result = execute_update(
                    instrument,
                    package,
                    destructive_authorized=True,
                    reboot_updateimage=False,
                    progress=self._progress_callback("Uploading patched SA96"),
                )
                completion = complete_identity_switch_after_end(
                    instrument,
                    plan,
                    progress=self._progress_callback("Verifying programmed SA96"),
                    status=lambda message: self.events.put(("indeterminate", message)),
                )
                result = {
                    "status": "COMPLETED_AND_READBACK_VERIFIED",
                    "backupFolder": str(folder),
                    "fullServiceBackupCreated": full_backup,
                    "plan": plan.as_dict(),
                    "update": update_result,
                    **completion,
                }
                self._write_json(folder / "identity_switch_result.json", result)
                return result

        self._run_worker("Preparing identity switch", operation)


def main() -> None:
    ServiceUtilityGui().mainloop()
