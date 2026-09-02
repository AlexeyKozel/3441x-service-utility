"""Verified PC-side protocol for the 3441x `caspreRamBased` updater."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Callable, Protocol

from .srecord import XsPackage


@dataclass(frozen=True)
class UpdateBlock:
    index: int
    total: int
    payload: bytes
    command_without_terminator: bytes

    @property
    def wire_bytes(self) -> bytes:
        return self.command_without_terminator + b"\n"


def selector_start_command(package: XsPackage) -> str:
    return (
        f':diag:upd:start? {package.selector}, '
        f'"loader_{package.model}","0",0,0'
    )


def normalize_payload_like_factory(payload: bytes) -> bytes:
    """Emulate the native updater's Windows text-mode read of an XS stream.

    FirmwareUpdateUtility B.01.09 opens the package with mode ``"r"`` before
    measuring and chunking it. The Windows CRT therefore converts CRLF to LF.
    Preserve lone CR and lone LF exactly; only CRLF pairs are translated.
    """
    return payload.replace(b"\r\n", b"\n")


def split_payload_like_factory(package: XsPackage, block_size: int) -> list[bytes]:
    payload = normalize_payload_like_factory(package.payload)
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    line_lengths = [len(line) for line in payload.splitlines(keepends=True)]
    if not line_lengths or not payload.endswith(b"\n"):
        raise ValueError("S-record stream must end with LF")
    max_line = max(line_lengths)
    target = block_size if len(payload) <= block_size else block_size - 2 * max_line
    if target <= 0:
        raise ValueError("block_size is too small for the longest S-record line")

    chunks: list[bytes] = []
    position = 0
    while position < len(payload):
        end = min(position + target, len(payload))
        if end < len(payload):
            newline = payload.find(b"\n", end)
            if newline < 0:
                end = len(payload)
            else:
                end = newline + 1
        chunks.append(payload[position:end])
        position = end
    return chunks


def build_update_blocks(package: XsPackage, block_size: int) -> list[UpdateBlock]:
    chunks = split_payload_like_factory(package, block_size)
    normalized_payload = normalize_payload_like_factory(package.payload)
    declared_total = ceil(len(normalized_payload) / block_size)
    if len(chunks) != declared_total:
        raise ValueError(
            "factory chunking produced a chunk count that does not match "
            "the declared total; upload is blocked"
        )
    blocks: list[UpdateBlock] = []
    for index, payload in enumerate(chunks, start=1):
        length_text = str(len(payload)).encode("ascii")
        definite = b"#" + str(len(length_text)).encode("ascii") + length_text
        prefix = (
            f":diag:update:block? {index}, {declared_total}, ".encode("ascii")
            + definite
        )
        blocks.append(
            UpdateBlock(
                index=index,
                total=declared_total,
                payload=payload,
                command_without_terminator=prefix + payload,
            )
        )
    return blocks


class UpdateTransport(Protocol):
    def query_text(self, command: str) -> str: ...
    def write_text(self, command: str) -> None: ...
    def exchange_raw(self, wire_bytes: bytes) -> str: ...
    def reconnect(self) -> None: ...


def parse_zero_status(response: str, *, phase: str) -> None:
    text = response.strip()
    try:
        status = int(text, 10)
    except ValueError as exc:
        raise RuntimeError(f"{phase}: expected a decimal status, received {text!r}") from exc
    if status != 0:
        raise RuntimeError(f"{phase}: instrument returned status {status}")


def parse_nonnegative_scpi_integer(response: str, *, phase: str) -> int:
    """Parse an integer SCPI response, including the standard leading `+`."""
    text = response.strip()
    try:
        value = int(text, 10)
    except ValueError as exc:
        raise RuntimeError(
            f"{phase}: expected a decimal integer, received {text!r}"
        ) from exc
    if value < 0:
        raise RuntimeError(f"{phase}: expected a non-negative integer, received {value}")
    return value


def dry_run_transcript(package: XsPackage, block_size: int) -> list[dict[str, object]]:
    blocks = build_update_blocks(package, block_size)
    events: list[dict[str, object]] = []
    if package.image_type == "instrumentimage":
        events.extend(
            [
                {"phase": "enter_loader", "command": ":diag:upd:reb"},
                {"phase": "reconnect", "expected_identity": f"loader_{package.model}"},
            ]
        )
    events.append({"phase": "start", "command": selector_start_command(package)})
    events.append(
        {
            "phase": "block_size",
            "command": ":diag:upd:block:size?",
            "assumed_response": str(block_size),
        }
    )
    events.extend(
        {
            "phase": "block",
            "index": block.index,
            "total": block.total,
            "payload_bytes": len(block.payload),
            "wire_bytes": len(block.wire_bytes),
            "prefix": block.command_without_terminator[: block.command_without_terminator.find(b"S")].decode("ascii"),
            "expected_response": "0",
        }
        for block in blocks
    )
    events.extend(
        [
            {"phase": "checksum", "command": "diag:upd:csum?"},
            {"phase": "end", "command": ":diag:upd:end? <checksum>"},
        ]
    )
    if package.image_type == "updateimage":
        events.append({"phase": "reboot", "command": ":diag:reboot"})
    else:
        events.append({"phase": "reconnect", "expected_identity": package.model})
    return events


class FactoryProtocolEmulator:
    """Strict receiving-side emulator for offline tests."""

    def __init__(self, package: XsPackage, block_size: int):
        self.package = package
        self.block_size = block_size
        self.expected_blocks = build_update_blocks(package, block_size)
        self.events: list[str] = []
        self._next_block = 0
        self._started = False
        self._ended = False

    def query_text(self, command: str) -> str:
        if command == ":diag:upd:block:size?":
            self.events.append("block_size")
            return str(self.block_size)
        if command == selector_start_command(self.package):
            if self._started:
                raise RuntimeError("duplicate START")
            self._started = True
            self.events.append("start")
            return "0"
        if command == "diag:upd:csum?":
            if self._next_block != len(self.expected_blocks):
                raise RuntimeError("CSUM requested before all blocks")
            self.events.append("checksum")
            return "305419896"
        if command == ":diag:upd:end? 305419896":
            if self._ended:
                raise RuntimeError("duplicate END")
            self._ended = True
            self.events.append("end")
            return "0"
        raise RuntimeError(f"unexpected command {command!r}")

    def write_text(self, command: str) -> None:
        if command not in {":diag:upd:reb", ":diag:reboot"}:
            raise RuntimeError(f"unexpected write-only command {command!r}")
        self.events.append(command)

    def exchange_raw(self, wire_bytes: bytes) -> str:
        if not self._started:
            raise RuntimeError("BLOCK received before START")
        expected = self.expected_blocks[self._next_block].wire_bytes
        if wire_bytes != expected:
            raise RuntimeError(f"block {self._next_block + 1} differs byte-for-byte")
        self._next_block += 1
        self.events.append(f"block:{self._next_block}")
        return "0"

    def reconnect(self) -> None:
        self.events.append("reconnect")


def execute_emulated(package: XsPackage, block_size: int) -> FactoryProtocolEmulator:
    transport = FactoryProtocolEmulator(package, block_size)
    if package.image_type == "instrumentimage":
        transport.write_text(":diag:upd:reb")
        transport.reconnect()
    parse_zero_status(
        transport.query_text(selector_start_command(package)), phase="start"
    )
    reported_block_size = parse_nonnegative_scpi_integer(
        transport.query_text(":diag:upd:block:size?"), phase="block_size"
    )
    if reported_block_size == 0:
        raise RuntimeError("block_size: instrument returned zero")
    if reported_block_size != block_size:
        raise RuntimeError("emulator returned an unexpected block size")
    for block in build_update_blocks(package, reported_block_size):
        parse_zero_status(
            transport.exchange_raw(block.wire_bytes), phase=f"block {block.index}"
        )
    checksum = str(
        parse_nonnegative_scpi_integer(
            transport.query_text("diag:upd:csum?"), phase="checksum"
        )
    )
    parse_zero_status(
        transport.query_text(f":diag:upd:end? {checksum}"), phase="end"
    )
    if package.image_type == "updateimage":
        transport.write_text(":diag:reboot")
    else:
        transport.reconnect()
    return transport


def execute_update(
    transport: UpdateTransport,
    package: XsPackage,
    *,
    destructive_authorized: bool,
    reboot_updateimage: bool = True,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    """Run the verified sequence without ambiguous block retries.

    This flag is not a user-confirmation policy. The caller must independently
    verify identity, backup state and an explicit user confirmation.
    """
    if not destructive_authorized:
        raise PermissionError("destructive firmware transport is not authorized")
    completed_blocks = 0
    phase = "preflight"
    try:
        if package.image_type == "instrumentimage":
            phase = "enter_loader"
            transport.write_text(":diag:upd:reb")
            transport.reconnect()
        phase = "start"
        parse_zero_status(
            transport.query_text(selector_start_command(package)), phase=phase
        )
        phase = "block_size"
        block_size = parse_nonnegative_scpi_integer(
            transport.query_text(":diag:upd:block:size?"), phase=phase
        )
        if block_size == 0:
            raise RuntimeError("block_size: instrument returned zero")
        blocks = build_update_blocks(package, block_size)
        total_payload = sum(len(block.payload) for block in blocks)
        completed_payload = 0
        if progress:
            progress(0, total_payload)
        for block in blocks:
            phase = f"block:{block.index}/{block.total}"
            parse_zero_status(transport.exchange_raw(block.wire_bytes), phase=phase)
            completed_blocks = block.index
            completed_payload += len(block.payload)
            if progress:
                progress(completed_payload, total_payload)
        phase = "checksum"
        checksum = str(
            parse_nonnegative_scpi_integer(
                transport.query_text("diag:upd:csum?"), phase=phase
            )
        )
        phase = "end"
        parse_zero_status(
            transport.query_text(f":diag:upd:end? {checksum}"), phase=phase
        )
        result_status = "completed"
        if package.image_type == "updateimage" and reboot_updateimage:
            phase = "reboot"
            transport.write_text(":diag:reboot")
        elif package.image_type == "instrumentimage":
            phase = "manual_power_cycle_required"
            result_status = "payload_accepted_manual_power_cycle_required"
        return {
            "status": result_status,
            "blockSize": block_size,
            "blocks": len(blocks),
            "checksum": checksum,
            "lastPhase": phase,
        }
    except Exception as exc:
        raise RuntimeError(
            f"update stopped in phase {phase}; accepted blocks={completed_blocks}; "
            "instrument state must be checked: "
            f"{exc}"
        ) from exc
