"""Session-bound construction of native SA96 identity-switch packages."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from .srecord import build_xs, parse_xs_bytes


REC_BASE = 0xFFE00000
SA96_SIZE = 0x10000
PERSONALITY_ADDRESS = 0xFFE0230E
PERSONALITY_OFFSET = PERSONALITY_ADDRESS - REC_BASE
PERSONALITY = {"34410A": 0x235A, "34411A": 0xB643}
MODEL_BY_VALUE = {value: model for model, value in PERSONALITY.items()}
WRITER_SUFFIX = bytes.fromhex("3C8090003884000AB0640000")


def default_backup_root() -> Path:
    """Return the backup directory beside the launched utility files."""

    return Path(__file__).resolve().parents[1] / "3441x Service Utility Backups"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _be32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _sum32(data: bytes, start: int, end_inclusive: int) -> int:
    length = end_inclusive - start + 1
    if length <= 0 or length % 4:
        raise ValueError("invalid Recovery SUM32 span")
    return sum(_be32(data, offset) for offset in range(start, end_inclusive + 1, 4)) & 0xFFFFFFFF


@dataclass(frozen=True)
class FreshInstrumentSnapshot:
    session_id: str
    resource: str
    idn: str
    serial: str
    current_model: str
    app_revision: str
    recovery_revision: str
    recovery: bytes
    captured_at_utc: str
    source: str = "instrument-current-session"

    def validate_origin(self) -> None:
        if self.source != "instrument-current-session":
            raise ValueError("SA96/Recovery must come from the current instrument session")
        if not self.session_id or not self.resource or not self.serial:
            raise ValueError("snapshot is not bound to an instrument session")
        if self.current_model not in PERSONALITY:
            raise ValueError("identity switching is supported only for 34410A/34411A")


@dataclass(frozen=True)
class FreshSa96Snapshot:
    session_id: str
    resource: str
    idn: str
    serial: str
    current_model: str
    app_revision: str
    sa96: bytes
    captured_at_utc: str
    recovery_revision: str = "native"
    source: str = "instrument-current-session"

    def validate_origin(self) -> None:
        if self.source != "instrument-current-session":
            raise ValueError("SA96 must come from the current instrument session")
        if not self.session_id or not self.resource or not self.serial:
            raise ValueError("snapshot is not bound to an instrument session")
        if self.current_model not in PERSONALITY:
            raise ValueError("identity switching is supported only for 34410A/34411A")
        if len(self.sa96) != SA96_SIZE:
            raise ValueError("SA96 snapshot must contain exactly 65536 bytes")


# Which APP images validate the boot personality at startup.
#
#   34411A APP : reads 0x9000000A and requires 0xB643. On anything else it
#                displays PLEASE LOAD / 34410 FIRMWARE and stops in the loader.
#   34410A APP : contains no such check at all -- verified by searching both
#                decompressed images for the comparison and for the message
#                string. It starts on either personality.
#
# So switching personality is safe while a 34410A APP is installed, and leaves
# the instrument unable to start while a 34411A APP is installed. That is a
# reason to WARN, not a reason to refuse: passing through a state where the APP
# and the personality disagree is unavoidable in any conversion, and refusing
# it strands the operator with no way back.
APP_VALIDATES_PERSONALITY = {"34410A": False, "34411A": True}


def app_starts_on_personality(app_model: str | None, personality_model: str | None) -> bool | None:
    """True/False if known, None if the APP image is unrecognised."""

    validates = APP_VALIDATES_PERSONALITY.get(app_model or "")
    if validates is None:
        return None
    return True if not validates else app_model == personality_model


@dataclass(frozen=True)
class IdentityWritePlan:
    snapshot: FreshInstrumentSnapshot | FreshSa96Snapshot
    target_model: str
    source_personality: int
    target_personality: int
    source_sa96: bytes
    target_sa96: bytes
    source_recovery_sha256: str | None
    target_recovery_sha256: str | None
    package_bytes: bytes
    changed_recovery_offsets: tuple[int, ...]
    checksum_policy: str
    full_recovery_checksum_verified: bool

    @property
    def installed_app_model(self) -> str:
        return self.snapshot.current_model

    @property
    def resulting_state_starts(self) -> bool | None:
        return app_starts_on_personality(self.installed_app_model, self.target_model)

    @property
    def warning(self) -> str | None:
        starts = self.resulting_state_starts
        if starts is None:
            return (
                f"The installed APP reports {self.installed_app_model}, which is "
                "not a recognised 3441x APP image. Whether it will start on a "
                f"{self.target_model} boot personality is unknown."
            )
        if starts:
            return None
        return (
            f"After this switch the installed {self.installed_app_model} APP will "
            f"REFUSE TO START on a {self.target_model} boot personality: it will "
            f"display PLEASE LOAD / {self.target_model[:5]} FIRMWARE and stop in "
            f"the loader. Upload the original {self.target_model} APP image to "
            "finish. The instrument stays recoverable throughout -- the loader "
            "is the mode that accepts a firmware load -- but it will not measure "
            "until the APP is replaced."
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "createdAtUtc": datetime.now(timezone.utc).isoformat(),
            "sessionId": self.snapshot.session_id,
            "resource": self.snapshot.resource,
            "idn": self.snapshot.idn,
            "serial": self.snapshot.serial,
            "appRevision": self.snapshot.app_revision,
            "recoveryRevision": self.snapshot.recovery_revision,
            "sourceModel": MODEL_BY_VALUE[self.source_personality],
            "targetModel": self.target_model,
            "sourcePersonality": f"0x{self.source_personality:04X}",
            "targetPersonality": f"0x{self.target_personality:04X}",
            "sourceSa96Sha256": _sha256(self.source_sa96),
            "targetSa96Sha256": _sha256(self.target_sa96),
            "sourceRecoverySha256": self.source_recovery_sha256,
            "targetRecoverySha256": self.target_recovery_sha256,
            "packageSha256": _sha256(self.package_bytes),
            "changedCpuAddresses": [
                f"0x{REC_BASE + offset:08X}" for offset in self.changed_recovery_offsets
            ],
            "originPolicy": "instrument-current-session-only",
            "checksumPolicy": self.checksum_policy,
            "fullRecoveryChecksumVerified": self.full_recovery_checksum_verified,
            "installedAppModel": self.installed_app_model,
            "appAndPersonalityAgreedBefore":
                self.installed_app_model == MODEL_BY_VALUE[self.source_personality],
            "resultingStateStarts": self.resulting_state_starts,
            "warning": self.warning,
        }


def _validate_recovery(recovery: bytes) -> tuple[int, int]:
    if len(recovery) < SA96_SIZE:
        raise ValueError("a complete logical Recovery image is required")
    stored = _be32(recovery, 0)
    end_address = _be32(recovery, 4)
    if not REC_BASE + 0x10 <= end_address <= 0xFFFFFFFF:
        raise ValueError(f"invalid Recovery endAddress 0x{end_address:08X}")
    end_offset = end_address - REC_BASE
    if end_offset >= len(recovery):
        raise ValueError("Recovery snapshot is shorter than endAddress")
    calculated = _sum32(recovery, 0x10, end_offset)
    if stored != calculated:
        raise ValueError(
            f"Recovery checksum failed: stored=0x{stored:08X}, "
            f"calculated=0x{calculated:08X}"
        )
    return end_offset, stored


def _find_personality_writer(recovery: bytes, end_offset: int) -> tuple[int, int]:
    hits: list[tuple[int, int]] = []
    for offset in range(0, end_offset - 15, 4):
        if recovery[offset : offset + 2] == b"\x38\x60" and recovery[offset + 4 : offset + 16] == WRITER_SUFFIX:
            hits.append((offset + 2, int.from_bytes(recovery[offset + 2 : offset + 4], "big")))
    if len(hits) != 1:
        raise ValueError(f"expected one personality writer, found {len(hits)}")
    immediate_offset, value = hits[0]
    if immediate_offset != PERSONALITY_OFFSET:
        raise ValueError(
            f"personality immediate was found at an unexpected address "
            f"0x{REC_BASE + immediate_offset:08X}"
        )
    if value not in MODEL_BY_VALUE:
        raise ValueError(f"unknown personality 0x{value:04X}")
    return immediate_offset, value


def _build_sa96_package(
    *, source_model: str, target_model: str, image_revision: str, target_sa96: bytes
) -> bytes:
    # The factory CONTROL/PATCH vectors deliberately omit BootImageHeader
    # reserved bytes at SA96+0x08..0x0F. Preserve that exact policy.
    records = [(REC_BASE, target_sa96[:8])]
    records.extend(
        (REC_BASE + offset, target_sa96[offset : offset + 16])
        for offset in range(0x10, SA96_SIZE, 16)
    )
    return build_xs(
        model=source_model,
        image_type="updateimage",
        image_revision=image_revision,
        description=(
            f"Session-bound native SA96 identity switch "
            f"{source_model} to {target_model}"
        ),
        s3_records=records,
    )


def _validate_sa96_package(package: bytes) -> None:
    parsed = parse_xs_bytes(package)
    if parsed.s3_records[0].address != REC_BASE:
        raise RuntimeError("internal error: package does not start at SA96")
    last = parsed.s3_records[-1]
    if last.address + len(last.data) != REC_BASE + SA96_SIZE:
        raise RuntimeError("internal error: package does not end at the SA96 boundary")


def build_identity_write_plan(
    snapshot: FreshInstrumentSnapshot, target_model: str
) -> IdentityWritePlan:
    snapshot.validate_origin()
    if target_model not in PERSONALITY:
        raise ValueError("target_model must be 34410A or 34411A")
    recovery = snapshot.recovery
    end_offset, _ = _validate_recovery(recovery)
    immediate_offset, source_value = _find_personality_writer(recovery, end_offset)
    # The installed APP and the boot personality are allowed to disagree.
    # Every conversion passes through exactly that state, because an identity
    # switch does not replace the APP -- afterwards *IDN? still reports the old
    # model. Refusing it stranded the operator: having switched, a switch back
    # was rejected, and the only way out was a full conversion followed by a
    # full reversal, two APP uploads. See IdentityWritePlan.warning, which says
    # whether the resulting combination will start.
    target_value = PERSONALITY[target_model]
    if target_value == source_value:
        raise ValueError("the requested identity is already active")

    patched = bytearray(recovery)
    patched[immediate_offset : immediate_offset + 2] = target_value.to_bytes(2, "big")
    checksum = _sum32(patched, 0x10, end_offset)
    struct.pack_into(">I", patched, 0, checksum)
    target_recovery = bytes(patched)
    _validate_recovery(target_recovery)

    changed = tuple(
        index for index, (before, after) in enumerate(zip(recovery, target_recovery)) if before != after
    )
    allowed = frozenset({0, 1, 2, 3, immediate_offset, immediate_offset + 1})
    if not changed or not set(changed).issubset(allowed):
        raise RuntimeError("identity patch changed bytes outside the allowed set")

    source_sa96 = recovery[:SA96_SIZE]
    target_sa96 = target_recovery[:SA96_SIZE]
    package = _build_sa96_package(
        source_model=snapshot.current_model,
        target_model=target_model,
        image_revision=snapshot.recovery_revision,
        target_sa96=target_sa96,
    )
    _validate_sa96_package(package)

    return IdentityWritePlan(
        snapshot=snapshot,
        target_model=target_model,
        source_personality=source_value,
        target_personality=target_value,
        source_sa96=source_sa96,
        target_sa96=target_sa96,
        source_recovery_sha256=_sha256(recovery),
        target_recovery_sha256=_sha256(target_recovery),
        package_bytes=package,
        changed_recovery_offsets=changed,
        checksum_policy="full-recovery-sum32-verified",
        full_recovery_checksum_verified=True,
    )


def build_sa96_identity_write_plan(
    snapshot: FreshSa96Snapshot, target_model: str
) -> IdentityWritePlan:
    """Build a fast plan from native SA96 using an exact SUM32 word delta.

    This mode cannot independently recompute the full Recovery checksum. It
    preserves the stored full-image SUM32 by subtracting the original PPC word
    and adding the patched word. The original SA96 is always retained for
    rollback evidence before any write is permitted.
    """

    snapshot.validate_origin()
    if target_model not in PERSONALITY:
        raise ValueError("target_model must be 34410A or 34411A")
    source_sa96 = snapshot.sa96
    stored_checksum = _be32(source_sa96, 0)
    end_address = _be32(source_sa96, 4)
    if not REC_BASE + SA96_SIZE <= end_address <= 0xFFFFFFFF:
        raise ValueError(f"invalid Recovery endAddress 0x{end_address:08X}")
    immediate_offset, source_value = _find_personality_writer(
        source_sa96, SA96_SIZE - 1
    )
    # The installed APP and the boot personality are allowed to disagree.
    # Every conversion passes through exactly that state, because an identity
    # switch does not replace the APP -- afterwards *IDN? still reports the old
    # model. Refusing it stranded the operator: having switched, a switch back
    # was rejected, and the only way out was a full conversion followed by a
    # full reversal, two APP uploads. See IdentityWritePlan.warning, which says
    # whether the resulting combination will start.
    target_value = PERSONALITY[target_model]
    if target_value == source_value:
        raise ValueError("the requested identity is already active")

    patched = bytearray(source_sa96)
    word_offset = immediate_offset - 2
    source_word = _be32(source_sa96, word_offset)
    patched[immediate_offset : immediate_offset + 2] = target_value.to_bytes(2, "big")
    target_word = _be32(patched, word_offset)
    target_checksum = (stored_checksum - source_word + target_word) & 0xFFFFFFFF
    struct.pack_into(">I", patched, 0, target_checksum)
    target_sa96 = bytes(patched)
    changed = tuple(
        index
        for index, (before, after) in enumerate(zip(source_sa96, target_sa96))
        if before != after
    )
    allowed = frozenset({0, 1, 2, 3, immediate_offset, immediate_offset + 1})
    if not changed or not set(changed).issubset(allowed):
        raise RuntimeError("identity patch changed bytes outside the allowed set")

    package = _build_sa96_package(
        source_model=snapshot.current_model,
        target_model=target_model,
        image_revision=snapshot.recovery_revision,
        target_sa96=target_sa96,
    )
    _validate_sa96_package(package)
    return IdentityWritePlan(
        snapshot=snapshot,
        target_model=target_model,
        source_personality=source_value,
        target_personality=target_value,
        source_sa96=source_sa96,
        target_sa96=target_sa96,
        source_recovery_sha256=None,
        target_recovery_sha256=None,
        package_bytes=package,
        changed_recovery_offsets=changed,
        checksum_policy="stored-recovery-sum32-word-delta",
        full_recovery_checksum_verified=False,
    )


def assert_fresh_readback_before_write(plan: IdentityWritePlan, current_sa96: bytes) -> None:
    if len(current_sa96) != SA96_SIZE:
        raise ValueError("fresh SA96 read-back has an invalid size")
    if current_sa96 != plan.source_sa96:
        raise RuntimeError("SA96 changed after plan creation; operation cancelled")


def assert_programmed_readback(plan: IdentityWritePlan, programmed_sa96: bytes) -> None:
    if programmed_sa96 != plan.target_sa96:
        raise RuntimeError("programmed SA96 does not match the target; reboot is blocked")


class IdentityCompletionInstrument(Protocol):
    def read_memory(
        self,
        address: int,
        size: int,
        *,
        batch_words: int = 16,
        progress: Callable[[int, int], None] | None = None,
    ) -> bytes: ...

    def identity(self) -> dict[str, str]: ...

    def write_text(self, command: str) -> None: ...

    def reconnect(self) -> None: ...


def complete_identity_switch_after_end(
    instrument: IdentityCompletionInstrument,
    plan: IdentityWritePlan,
    *,
    progress: Callable[[int, int], None] | None = None,
    status: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Verify programmed SA96 across either automatic or explicit reboot.

    A real 3441x may reboot automatically after updater END and interrupt the
    first read-back. This recovery path never repeats START or any data block:
    it reconnects and starts a new, complete read-only SA96 comparison.
    """

    def report(message: str) -> None:
        if status is not None:
            status(message)

    initial_error: str | None = None
    automatic_reboot_detected = False
    try:
        programmed_sa96 = instrument.read_memory(
            REC_BASE, SA96_SIZE, batch_words=64, progress=progress
        )
    except Exception as exc:
        initial_error = f"{type(exc).__name__}: {exc}"
        automatic_reboot_detected = True
        report("SA96 read-back interrupted; reconnecting after automatic reboot")
        instrument.reconnect()
        identity_after = instrument.identity()
        report("Re-reading complete SA96 after reconnect")
        programmed_sa96 = instrument.read_memory(
            REC_BASE, SA96_SIZE, batch_words=64, progress=progress
        )
        assert_programmed_readback(plan, programmed_sa96)
    else:
        # A complete but different sector is a hard failure. It must not be
        # converted into a reconnect/retry condition.
        assert_programmed_readback(plan, programmed_sa96)
        try:
            identity_after = instrument.identity()
        except Exception:
            automatic_reboot_detected = True
            report("Instrument reboot detected; reconnecting")
            instrument.reconnect()
            identity_after = instrument.identity()

    source_model = MODEL_BY_VALUE[plan.source_personality]
    expected_serial = plan.snapshot.serial
    if identity_after.get("serial") != expected_serial:
        raise RuntimeError("Post-END instrument serial does not match the write plan")

    model_after = identity_after.get("model")
    # A loader identity is a third valid outcome, not a failure. Writing SA96
    # reboots the instrument, and if the installed APP validates the boot
    # personality it refuses the new one: the 34411A APP requires 0xB643, so it
    # displays PLEASE LOAD / 34410 FIRMWARE and stops in the loader. (The
    # 34410A APP has no such check and simply starts.) A 34411A -> 34410A
    # switch therefore legitimately ends with the instrument reporting
    # `loader_34410A`, which is neither the source nor the target model.
    #
    # Reaching the loader is itself evidence the write took effect: the APP
    # refuses only when it reads a personality that is not its own.
    in_loader = str(model_after or "").startswith("loader_")
    if not in_loader and model_after not in {source_model, plan.target_model}:
        raise RuntimeError("Post-END instrument model does not match the write plan")

    if in_loader or automatic_reboot_detected or model_after == plan.target_model:
        # In the loader case the instrument has already rebooted and there is
        # nothing else for it to boot into. Do not issue a second reboot.
        reboot_mode = "automatic"
    else:
        report("Rebooting and reconnecting")
        try:
            instrument.write_text(":diag:reboot")
        except Exception:
            # Automatic reboot may begin between the identity query and this
            # command. Do not repeat it; reconnect and verify instead.
            pass
        instrument.reconnect()
        identity_after = instrument.identity()
        reboot_mode = "explicit"
        if identity_after.get("serial") != expected_serial:
            raise RuntimeError("Post-reboot identity does not match the write plan")
        model_after = identity_after.get("model")
        if model_after not in {source_model, plan.target_model}:
            raise RuntimeError("Post-reboot identity does not match the write plan")

    app_identity_pending = in_loader or model_after != plan.target_model
    if app_identity_pending:
        report(
            f"Boot identity verified; upload the original {plan.target_model} APP image"
        )
    if in_loader:
        report(
            "The installed APP refused the new boot personality and the loader "
            "is now in charge. The instrument will not measure until the "
            f"{plan.target_model} APP image is uploaded; it is recoverable, "
            "because the loader is the mode that accepts a firmware load."
        )

    return {
        "identityAfter": identity_after,
        "rebootMode": reboot_mode,
        "initialReadbackInterrupted": initial_error is not None,
        "initialReadbackError": initial_error,
        "postEndSa96ReadbackVerified": True,
        "instrumentInLoader": in_loader,
        "appIdentityPending": app_identity_pending,
        "requiredAppModel": plan.target_model if app_identity_pending else None,
        "nextAction": (
            f"Upload the original {plan.target_model} APP image"
            if app_identity_pending
            else None
        ),
    }
