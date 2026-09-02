from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.identity import (  # noqa: E402
    FreshInstrumentSnapshot,
    FreshSa96Snapshot,
    REC_BASE,
    assert_fresh_readback_before_write,
    assert_programmed_readback,
    build_identity_write_plan,
    build_sa96_identity_write_plan,
    complete_identity_switch_after_end,
    default_backup_root,
)
from utility3441x.srecord import parse_xs_bytes  # noqa: E402
from utility3441x.update_protocol import build_update_blocks  # noqa: E402


def synthetic_recovery() -> bytes:
    image = bytearray(0x12000)
    struct.pack_into(">I", image, 4, REC_BASE + len(image) - 1)
    writer = bytes.fromhex("3860235A3C8090003884000AB0640000")
    image[0x230C : 0x230C + len(writer)] = writer
    checksum = sum(
        struct.unpack_from(">I", image, offset)[0]
        for offset in range(0x10, len(image), 4)
    ) & 0xFFFFFFFF
    struct.pack_into(">I", image, 0, checksum)
    return bytes(image)


def snapshot(*, source: str = "instrument-current-session") -> FreshInstrumentSnapshot:
    return FreshInstrumentSnapshot(
        session_id="session-1",
        resource="TCPIP0::192.0.2.1::inst0::INSTR",
        idn="Agilent Technologies,34410A,MY00000001,2.43",
        serial="MY00000001",
        current_model="34410A",
        app_revision="2.43",
        recovery_revision="2.35",
        recovery=synthetic_recovery(),
        captured_at_utc="2026-08-30T00:00:00Z",
        source=source,
    )


class IdentityPlanTests(unittest.TestCase):
    def test_native_sector_plan_and_package(self):
        plan = build_identity_write_plan(snapshot(), "34411A")
        self.assertEqual(plan.source_sa96[0x230E:0x2310], bytes.fromhex("235A"))
        self.assertEqual(plan.target_sa96[0x230E:0x2310], bytes.fromhex("B643"))
        self.assertTrue(
            set(plan.changed_recovery_offsets).issubset({0, 1, 2, 3, 0x230E, 0x230F})
        )
        package = parse_xs_bytes(plan.package_bytes)
        self.assertEqual(package.model, "34410A")
        self.assertEqual(package.image_type, "updateimage")
        self.assertEqual(len(package.s3_records), 4096)
        self.assertEqual(len(package.s3_records[0].data), 8)
        self.assertEqual(package.s3_records[1].address, REC_BASE + 0x10)
        self.assertEqual(
            b"".join(record.data for record in package.s3_records),
            plan.target_sa96[:8] + plan.target_sa96[16:],
        )
        self.assertIn(b"\r\n", package.payload)
        blocks = build_update_blocks(package, 50000)
        self.assertEqual(
            [len(block.payload) for block in blocks],
            [49913, 49914, 49914, 42783],
        )
        self.assertNotIn(b"\r", b"".join(block.payload for block in blocks))
        self.assertTrue(plan.full_recovery_checksum_verified)

    def test_fast_sa96_plan_matches_full_recovery_plan(self):
        full = build_identity_write_plan(snapshot(), "34411A")
        source = snapshot()
        fast_snapshot = FreshSa96Snapshot(
            session_id=source.session_id,
            resource=source.resource,
            idn=source.idn,
            serial=source.serial,
            current_model=source.current_model,
            app_revision=source.app_revision,
            recovery_revision=source.recovery_revision,
            sa96=source.recovery[:0x10000],
            captured_at_utc=source.captured_at_utc,
        )
        fast = build_sa96_identity_write_plan(fast_snapshot, "34411A")
        self.assertEqual(fast.target_sa96, full.target_sa96)
        self.assertEqual(fast.changed_recovery_offsets, full.changed_recovery_offsets)
        self.assertEqual(fast.package_bytes, full.package_bytes)
        self.assertFalse(fast.full_recovery_checksum_verified)
        self.assertEqual(fast.checksum_policy, "stored-recovery-sum32-word-delta")

    def test_non_session_origin_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "current instrument session"):
            build_identity_write_plan(snapshot(source="local-file"), "34411A")

    def test_stale_source_readback_is_rejected(self):
        plan = build_identity_write_plan(snapshot(), "34411A")
        stale = bytearray(plan.source_sa96)
        stale[0x100] ^= 1
        with self.assertRaisesRegex(RuntimeError, "changed"):
            assert_fresh_readback_before_write(plan, bytes(stale))

    def test_incorrect_programmed_readback_blocks_reboot(self):
        plan = build_identity_write_plan(snapshot(), "34411A")
        bad = bytearray(plan.target_sa96)
        bad[-1] ^= 1
        with self.assertRaisesRegex(RuntimeError, "reboot is blocked"):
            assert_programmed_readback(plan, bytes(bad))

    def test_default_backup_root_is_beside_utility(self):
        self.assertEqual(
            default_backup_root(),
            ROOT / "3441x Service Utility Backups",
        )

    def test_automatic_reboot_reconnects_and_restarts_full_readback(self):
        plan = build_identity_write_plan(snapshot(), "34411A")

        class AutomaticRebootInstrument:
            def __init__(self):
                self.reads = 0
                self.reconnects = 0
                self.writes: list[str] = []

            def read_memory(self, address, size, *, batch_words=16, progress=None):
                self.reads += 1
                if self.reads == 1:
                    raise TimeoutError("instrument rebooted at 50.8%")
                if progress:
                    progress(size, size)
                return plan.target_sa96

            def reconnect(self):
                self.reconnects += 1

            def identity(self):
                # The old APP keeps reporting the source model even though the
                # programmed SA96 boot personality is already the target.
                return {"model": "34410A", "serial": "MY00000001"}

            def write_text(self, command):
                self.writes.append(command)

        instrument = AutomaticRebootInstrument()
        result = complete_identity_switch_after_end(instrument, plan)
        self.assertEqual(instrument.reads, 2)
        self.assertEqual(instrument.reconnects, 1)
        self.assertEqual(instrument.writes, [])
        self.assertEqual(result["rebootMode"], "automatic")
        self.assertTrue(result["initialReadbackInterrupted"])
        self.assertTrue(result["postEndSa96ReadbackVerified"])
        self.assertTrue(result["appIdentityPending"])
        self.assertEqual(result["requiredAppModel"], "34411A")
        self.assertIn("34411A APP image", result["nextAction"])

    def test_explicit_reboot_is_used_when_instrument_is_still_source_model(self):
        plan = build_identity_write_plan(snapshot(), "34411A")

        class ExplicitRebootInstrument:
            def __init__(self):
                self.model = "34410A"
                self.reconnects = 0
                self.writes: list[str] = []

            def read_memory(self, address, size, *, batch_words=16, progress=None):
                return plan.target_sa96

            def reconnect(self):
                self.reconnects += 1

            def identity(self):
                return {"model": self.model, "serial": "MY00000001"}

            def write_text(self, command):
                self.writes.append(command)

        instrument = ExplicitRebootInstrument()
        result = complete_identity_switch_after_end(instrument, plan)
        self.assertEqual(instrument.writes, [":diag:reboot"])
        self.assertEqual(instrument.reconnects, 1)
        self.assertEqual(result["rebootMode"], "explicit")
        self.assertFalse(result["initialReadbackInterrupted"])
        self.assertTrue(result["appIdentityPending"])
        self.assertEqual(result["identityAfter"]["model"], "34410A")

    def test_target_app_identity_after_reboot_is_also_accepted(self):
        plan = build_identity_write_plan(snapshot(), "34411A")

        class TargetAppInstrument:
            def read_memory(self, address, size, *, batch_words=16, progress=None):
                return plan.target_sa96

            def reconnect(self):
                raise AssertionError("target APP identity already proves automatic reboot")

            def identity(self):
                return {"model": "34411A", "serial": "MY00000001"}

            def write_text(self, command):
                raise AssertionError("an additional reboot must not be sent")

        result = complete_identity_switch_after_end(TargetAppInstrument(), plan)
        self.assertEqual(result["rebootMode"], "automatic")
        self.assertFalse(result["appIdentityPending"])
        self.assertIsNone(result["requiredAppModel"])

    def test_mismatch_after_automatic_reboot_blocks_completion(self):
        plan = build_identity_write_plan(snapshot(), "34411A")
        bad = bytearray(plan.target_sa96)
        bad[-1] ^= 1

        class MismatchInstrument:
            reads = 0
            writes: list[str] = []

            def read_memory(self, address, size, *, batch_words=16, progress=None):
                self.reads += 1
                if self.reads == 1:
                    raise TimeoutError("automatic reboot")
                return bytes(bad)

            def reconnect(self):
                pass

            def identity(self):
                return {"model": "34411A", "serial": "MY00000001"}

            def write_text(self, command):
                self.writes.append(command)

        instrument = MismatchInstrument()
        with self.assertRaisesRegex(RuntimeError, "reboot is blocked"):
            complete_identity_switch_after_end(instrument, plan)
        self.assertEqual(instrument.writes, [])


if __name__ == "__main__":
    unittest.main()
