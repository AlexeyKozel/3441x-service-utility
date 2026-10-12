from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.srecord import (  # noqa: E402
    assert_app_identity_after,
    assert_app_image_package,
    assert_app_upload_preflight,
    build_xs,
    encode_srecord,
    load_xs,
    parse_xs_bytes,
)
from utility3441x.update_protocol import (  # noqa: E402
    FactoryProtocolEmulator,
    build_update_blocks,
    execute_emulated,
    execute_update,
    normalize_payload_like_factory,
    selector_start_command,
)




class SRecordProtocolTests(unittest.TestCase):
    def test_instrumentimage_requires_manual_power_cycle_without_reboot_command(self):
        package = parse_xs_bytes(
            build_xs(
                model="34411A",
                image_type="instrumentimage",
                image_revision="2.43",
                description="Synthetic APP completion",
                s3_records=[(0xFF880000, bytes(16))],
            )
        )
        transport = FactoryProtocolEmulator(package, 4096)
        result = execute_update(
            transport,
            package,
            destructive_authorized=True,
        )
        self.assertEqual(
            result["status"],
            "payload_accepted_manual_power_cycle_required",
        )
        self.assertEqual(result["lastPhase"], "manual_power_cycle_required")
        self.assertNotIn(":diag:reboot", transport.events)
        # No reboot into the loader, and therefore no reconnect. The factory
        # updater's caspreRamBased path sends START to whatever firmware is
        # already running: 0x40b9b8 jumps past the only ":diag:upd:reb" site in
        # the program. After END it asks for a manual power cycle rather than
        # reconnecting.
        self.assertNotIn(":diag:upd:reb", transport.events)
        self.assertEqual(transport.events.count("reconnect"), 0)

    def test_live_app_gate_accepts_only_instrumentimage(self):
        app = parse_xs_bytes(
            build_xs(
                model="34410A",
                image_type="instrumentimage",
                image_revision="2.43",
                description="Synthetic APP",
                s3_records=[(0xFF880000, bytes(16))],
            )
        )
        recovery = parse_xs_bytes(
            build_xs(
                model="34410A",
                image_type="updateimage",
                image_revision="2.35",
                description="Synthetic Recovery",
                s3_records=[(0xFFE00000, bytes(16))],
            )
        )
        assert_app_image_package(app)
        before = {"model": "34410A", "serial": "TEST00000001"}
        assert_app_upload_preflight(
            app,
            {"model": "34411A", "serial": "TEST00000001"},
        )
        assert_app_identity_after(
            app,
            before,
            {"model": "34410A", "serial": "TEST00000001"},
        )
        with self.assertRaisesRegex(RuntimeError, "identity does not match"):
            assert_app_identity_after(
                app,
                before,
                {"model": "34410A", "serial": "TEST99999999"},
            )
        with self.assertRaisesRegex(PermissionError, "updateimage upload is blocked"):
            assert_app_image_package(recovery)

        l4411_app = parse_xs_bytes(
            build_xs(
                model="L4411A",
                image_type="instrumentimage",
                image_revision="2.43",
                description="Synthetic L4411 APP",
                s3_records=[(0xFF880000, bytes(16))],
            )
        )
        with self.assertRaisesRegex(PermissionError, "only 34410A or 34411A"):
            assert_app_image_package(l4411_app)
        with self.assertRaisesRegex(PermissionError, "34410A/34411A instruments"):
            assert_app_upload_preflight(
                app,
                {"model": "L4411A", "serial": "TEST00000001"},
            )

    def test_synthetic_package_emulates_standalone(self):
        raw = build_xs(
            model="34410A",
            image_type="updateimage",
            image_revision="2.35",
            description="Synthetic test package",
            s3_records=[(0xFFE00000 + 16 * index, bytes([index]) * 16) for index in range(32)],
        )
        package = parse_xs_bytes(raw)
        emulator = execute_emulated(package, 65536)
        self.assertEqual(emulator.events, ["start", "block_size", "block:1", "checksum", "end", ":diag:reboot"])

    def test_generated_crlf_package_is_normalized_like_native_text_mode(self):
        raw = build_xs(
            model="34410A",
            image_type="updateimage",
            image_revision="2.35",
            description="Native text mode regression",
            s3_records=[
                (0xFFE00000 + 16 * index, bytes([index & 0xFF]) * 16)
                for index in range(256)
            ],
        )
        self.assertIn(b"\r\n", raw)
        package = parse_xs_bytes(raw)
        blocks = build_update_blocks(package, 4096)
        transmitted = b"".join(block.payload for block in blocks)
        self.assertEqual(transmitted, package.payload.replace(b"\r\n", b"\n"))
        self.assertNotIn(b"\r", transmitted)
        self.assertTrue(all(block.wire_bytes.endswith(b"\n\n") for block in blocks))

    def test_native_text_normalization_preserves_non_crlf_bytes(self):
        source = b"A\r\nB\nC\rD\r\n"
        self.assertEqual(normalize_payload_like_factory(source), b"A\nB\nC\rD\n")

    def test_s5_count_mismatch_is_rejected(self):
        raw = build_xs(
            model="34410A",
            image_type="updateimage",
            image_revision="2.35",
            description="Synthetic count test",
            s3_records=[(0xFFE00000, bytes(16))],
        )
        lines = raw.splitlines(keepends=True)
        lines[9] = encode_srecord("S5", (2).to_bytes(4, "big"))
        with self.assertRaisesRegex(ValueError, "record count"):
            parse_xs_bytes(b"".join(lines))

    def test_overlapping_address_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            build_xs(
                model="34410A",
                image_type="updateimage",
                image_revision="2.35",
                description="Synthetic address test",
                s3_records=[
                    (0xFFE00000, bytes(16)),
                    (0xFFE00008, bytes(16)),
                ],
            )

    def test_nonzero_block_response_stops_without_retry(self):
        raw = build_xs(
            model="34410A",
            image_type="updateimage",
            image_revision="2.35",
            description="Synthetic response test",
            s3_records=[(0xFFE00000, bytes(16))],
        )
        package = parse_xs_bytes(raw)

        class RejectingEmulator(FactoryProtocolEmulator):
            calls = 0

            def exchange_raw(self, wire_bytes: bytes) -> str:
                self.calls += 1
                return "7"

        transport = RejectingEmulator(package, 65536)
        with self.assertRaisesRegex(RuntimeError, "block:1/1"):
            execute_update(transport, package, destructive_authorized=True)
        self.assertEqual(transport.calls, 1)

    def test_timeout_stops_without_retry(self):
        raw = build_xs(
            model="34410A",
            image_type="updateimage",
            image_revision="2.35",
            description="Synthetic timeout test",
            s3_records=[(0xFFE00000, bytes(16))],
        )
        package = parse_xs_bytes(raw)

        class TimeoutEmulator(FactoryProtocolEmulator):
            calls = 0

            def exchange_raw(self, wire_bytes: bytes) -> str:
                self.calls += 1
                raise TimeoutError("synthetic timeout")

        transport = TimeoutEmulator(package, 65536)
        with self.assertRaisesRegex(RuntimeError, "synthetic timeout"):
            execute_update(transport, package, destructive_authorized=True)
        self.assertEqual(transport.calls, 1)

    def test_scpi_leading_plus_is_accepted_for_block_size_and_checksum(self):
        raw = build_xs(
            model="34410A",
            image_type="updateimage",
            image_revision="2.35",
            description="Signed SCPI integer response fixture",
            s3_records=[(0xFFE00000, bytes(16))],
        )
        package = parse_xs_bytes(raw)

        class PlusPrefixedEmulator(FactoryProtocolEmulator):
            def query_text(self, command: str) -> str:
                response = super().query_text(command)
                if command in {":diag:upd:block:size?", "diag:upd:csum?"}:
                    return f"+{response}"
                return response

        transport = PlusPrefixedEmulator(package, 50000)
        result = execute_update(
            transport,
            package,
            destructive_authorized=True,
            reboot_updateimage=False,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["blockSize"], 50000)
        self.assertEqual(result["checksum"], "305419896")






    def test_update_progress_is_monotonic_and_complete(self):
        raw = build_xs(
            model="34410A",
            image_type="updateimage",
            image_revision="2.35",
            description="Progress callback fixture",
            s3_records=[
                (0xFFE00000 + 16 * index, bytes([index & 0xFF]) * 16)
                for index in range(512)
            ],
        )
        package = parse_xs_bytes(raw)
        transport = FactoryProtocolEmulator(package, 4096)
        events = []
        execute_update(
            transport,
            package,
            destructive_authorized=True,
            reboot_updateimage=False,
            progress=lambda completed, total: events.append((completed, total)),
        )
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0][0], 0)
        self.assertEqual(events[-1][0], events[-1][1])
        self.assertEqual(events, sorted(events))


if __name__ == "__main__":
    unittest.main()
