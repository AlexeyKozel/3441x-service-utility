"""Supported VISA/SCPI reads and isolated updater transport."""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Callable

from .identity import FreshInstrumentSnapshot, FreshSa96Snapshot, REC_BASE, SA96_SIZE
from .offline import NOR_BASE, NOR_END, NOR_SIZE, inspect_recovery_bytes, parse_cal_payload


PROBE_ADDRESS = 0xFFE0230C
DIAGNOSTIC_QUERIES = {
    "data_path_free_buffers": "DIAG:PEEK:FIRMWARE? 6,0,0",
    "elapsed_runtime": "DIAG:PEEK:FIRMWARE? 24,0,0",
    "manufacturer_date_code": "DIAG:PEEK:FIRMWARE? 25,0,0",
}


def parse_u16_reply(text: str) -> int:
    value = text.strip().strip('"\'').strip()
    if value.lower().startswith("0x"):
        number = int(value, 16)
    elif re.fullmatch(r"[0-9A-Fa-f]+[hH]", value):
        number = int(value[:-1], 16)
    else:
        number = int(value, 10)
    if not 0 <= number <= 0xFFFF:
        raise ValueError("DIAG:PEEK reply is outside uint16")
    return number


def compose_peek_query(address: int, count: int) -> str:
    if address & 1 or not 1 <= count <= 64:
        raise ValueError("PEEK requires an even address and count 1..64")
    return "DIAG:" + ";".join(f"PEEK? {address + 2 * index}" for index in range(count))


def parse_idn(text: str) -> dict[str, str]:
    fields = [field.strip() for field in text.strip().split(",")]
    if len(fields) < 4:
        raise ValueError(f"unexpected *IDN? reply {text!r}")
    return {
        "manufacturer": fields[0],
        "model": fields[1],
        "serial": fields[2],
        "firmware": fields[3],
        "raw": text.strip(),
    }


class VisaInstrument:
    def __init__(self, resource: str, *, timeout_ms: int = 10_000):
        try:
            import pyvisa  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "the optional `pyvisa` package is required for instrument access"
            ) from exc
        self._pyvisa = pyvisa
        self.resource = resource
        self.timeout_ms = timeout_ms
        self.session_id = str(uuid.uuid4())
        self._rm = pyvisa.ResourceManager()
        self._inst = None
        self._open()

    def _open(self) -> None:
        self._inst = self._rm.open_resource(self.resource)
        self._inst.timeout = self.timeout_ms
        self._inst.write_termination = "\n"
        self._inst.read_termination = "\n"

    def close(self) -> None:
        try:
            if self._inst is not None:
                self._inst.close()
        finally:
            self._inst = None
            self._rm.close()

    def __enter__(self) -> "VisaInstrument":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def query_text(self, command: str) -> str:
        return str(self._inst.query(command)).rstrip("\r\n")

    def write_text(self, command: str) -> None:
        self._inst.write(command)

    def exchange_raw(self, wire_bytes: bytes) -> str:
        if not wire_bytes.endswith(b"\n"):
            raise ValueError("raw updater frame must end with LF")
        written = int(self._inst.write_raw(wire_bytes))
        if written != len(wire_bytes):
            raise RuntimeError(
                f"ambiguous short write {written}/{len(wire_bytes)}; retry is forbidden"
            )
        response = bytes(self._inst.read_raw())
        return response.decode("ascii", errors="strict").rstrip("\r\n")

    def reconnect(self, *, timeout_seconds: float = 90.0) -> None:
        if self._inst is not None:
            try:
                self._inst.close()
            except Exception:
                pass
        self._inst = None
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self._open()
                self.query_text("*IDN?")
                return
            except Exception as exc:  # VISA backend-specific exceptions
                last_error = exc
                if self._inst is not None:
                    try:
                        self._inst.close()
                    except Exception:
                        pass
                    self._inst = None
                time.sleep(1.0)
        raise TimeoutError(f"instrument did not reconnect after reboot: {last_error}")

    def identity(self) -> dict[str, str]:
        return parse_idn(self.query_text("*IDN?"))

    def diagnostics(self) -> dict[str, object]:
        identity = self.identity()
        values = {
            name: self.query_text(command)
            for name, command in DIAGNOSTIC_QUERIES.items()
        }
        probe = self.read_memory(PROBE_ADDRESS, 4)
        instruction = int.from_bytes(probe, "big")
        personality = {0x3860235A: "34410A", 0x3860B643: "34411A"}.get(instruction)
        return {
            "identity": identity,
            "diagnostics": values,
            "bootPersonalityInstruction": f"0x{instruction:08X}",
            "bootPersonalityModel": personality,
        }

    def read_memory(
        self,
        address: int,
        size: int,
        *,
        batch_words: int = 16,
        progress: Callable[[int, int], None] | None = None,
    ) -> bytes:
        if address & 1 or size <= 0 or size & 1:
            raise ValueError("memory read requires positive even address/size")
        if not NOR_BASE <= address <= NOR_END or address + size - 1 > NOR_END:
            raise ValueError("memory read is outside NOR")
        if not 1 <= batch_words <= 64:
            raise ValueError("batch_words must be 1..64")
        output = bytearray()
        cursor = address
        while len(output) < size:
            count = min(batch_words, (size - len(output)) // 2)
            response = self.query_text(compose_peek_query(cursor, count))
            parts = [part.strip() for part in response.split(";") if part.strip()]
            if len(parts) != count:
                raise RuntimeError(
                    f"DIAG:PEEK cardinality {len(parts)} instead of {count} at 0x{cursor:08X}"
                )
            values = [parse_u16_reply(part) for part in parts]
            block = b"".join(value.to_bytes(2, "big") for value in values)
            output.extend(block)
            cursor += len(block)
            if progress:
                progress(len(output), size)
        return bytes(output)

    def read_recovery(
        self, *, progress: Callable[[int, int], None] | None = None
    ) -> bytes:
        header = self.read_memory(REC_BASE, 16)
        end_address = int.from_bytes(header[4:8], "big")
        if not REC_BASE + 0x10 <= end_address <= NOR_END:
            raise RuntimeError(f"invalid Recovery endAddress 0x{end_address:08X}")
        size = end_address - REC_BASE + 1
        if size & 1:
            raise RuntimeError("Recovery has an odd size")
        recovery = self.read_memory(REC_BASE, size, batch_words=64, progress=progress)
        if recovery[:16] != header:
            raise RuntimeError("Recovery header changed while it was being read")
        return recovery

    def query_binary_block(self, command: str) -> bytes:
        old_termination = self._inst.read_termination
        try:
            self._inst.read_termination = None
            self._inst.write(command)
            prefix = bytes(self._inst.read_bytes(2))
            if len(prefix) != 2 or prefix[:1] != b"#":
                raise RuntimeError(f"invalid IEEE block prefix {prefix!r}")
            digits = prefix[1] - ord("0")
            if not 1 <= digits <= 9:
                raise RuntimeError("invalid IEEE block length digit count")
            length = int(bytes(self._inst.read_bytes(digits)).decode("ascii"), 10)
            payload = bytes(self._inst.read_bytes(length))
            if len(payload) != length:
                raise RuntimeError(f"short IEEE block {len(payload)}/{length}")
            return payload
        finally:
            self._inst.read_termination = old_termination

    def read_calibration(self) -> tuple[bytes, dict[str, object]]:
        payload = self.query_binary_block("CAL:DATA:ALL?")
        report = parse_cal_payload(payload)
        if not report["checksumValid"]:
            raise RuntimeError("CAL payload was received but its checksum failed")
        return payload, report

    def collect_identity_snapshot(self) -> FreshInstrumentSnapshot:
        identity = self.identity()
        recovery = self.read_recovery()
        recovery_report = inspect_recovery_bytes(recovery)
        embedded = recovery_report.get("embeddedRecovery") or {}
        recovery_revision = embedded.get("revision")
        if not embedded.get("known") or not isinstance(recovery_revision, str):
            raise RuntimeError(
                "Recovery build is not recognized by SHA-256; identity switch is blocked"
            )
        return FreshInstrumentSnapshot(
            session_id=self.session_id,
            resource=self.resource,
            idn=identity["raw"],
            serial=identity["serial"],
            current_model=identity["model"],
            app_revision=identity["firmware"],
            recovery_revision=recovery_revision,
            recovery=recovery,
            captured_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    def collect_sa96_snapshot(
        self, *, progress: Callable[[int, int], None] | None = None
    ) -> FreshSa96Snapshot:
        identity = self.identity()
        sa96 = self.read_memory(
            REC_BASE, SA96_SIZE, batch_words=64, progress=progress
        )
        return FreshSa96Snapshot(
            session_id=self.session_id,
            resource=self.resource,
            idn=identity["raw"],
            serial=identity["serial"],
            current_model=identity["model"],
            app_revision=identity["firmware"],
            sa96=sa96,
            captured_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )


def dump_nor(
    instrument: VisaInstrument,
    output: Path,
    *,
    resume: bool = True,
    batch_words: int = 16,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    output = Path(output)
    done = output.stat().st_size if resume and output.exists() else 0
    if done > NOR_SIZE or done & 1:
        raise ValueError("resume file has an invalid size")
    if done:
        verify_size = min(done, 256)
        with output.open("rb") as stream:
            stream.seek(done - verify_size)
            tail = stream.read(verify_size)
        current_tail = instrument.read_memory(NOR_BASE + done - verify_size, verify_size)
        if tail != current_tail:
            raise RuntimeError("resume tail does not match the current NOR")
    mode = "ab" if done else "wb"
    with output.open(mode) as stream:
        while done < NOR_SIZE:
            size = min(batch_words * 2, NOR_SIZE - done)
            block = instrument.read_memory(NOR_BASE + done, size, batch_words=batch_words)
            stream.write(block)
            done += len(block)
            if done % 0x10000 == 0:
                stream.flush()
                os.fsync(stream.fileno())
            if progress:
                progress(done, NOR_SIZE)
