from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x import (  # noqa: E402
    LIVE_APP_IMAGE_WRITE_ENABLED,
    LIVE_FIRMWARE_WRITE_ENABLED,
    LIVE_IDENTITY_WRITE_ENABLED,
)
from utility3441x.cli import build_parser  # noqa: E402
from utility3441x.offline import (  # noqa: E402
    SCHEMA45_BODY_BYTES,
    decode_schema45_body,
    inspect_nor_file,
    parse_cal_payload,
)


class OfflineAndSafetyTests(unittest.TestCase):
    def test_rc11_enables_bounded_identity_and_app_writes(self):
        self.assertFalse(LIVE_FIRMWARE_WRITE_ENABLED)
        self.assertTrue(LIVE_APP_IMAGE_WRITE_ENABLED)
        self.assertTrue(LIVE_IDENTITY_WRITE_ENABLED)

    def test_identity_cli_uses_boolean_confirmation(self):
        args = build_parser().parse_args(
            [
                "identity-switch",
                "--resource",
                "TCPIP0::example::inst0::INSTR",
                "--to",
                "34411A",
                "--execute",
                "--yes",
            ]
        )
        self.assertTrue(args.yes)
        self.assertFalse(hasattr(args, "confirm"))

    def test_app_cli_uses_boolean_confirmation(self):
        args = build_parser().parse_args(
            [
                "firmware-upload",
                "app.xs",
                "--resource",
                "TCPIP0::example::inst0::INSTR",
                "--execute",
                "--yes",
            ]
        )
        self.assertTrue(args.yes)
        self.assertFalse(hasattr(args, "confirm"))

    @unittest.skipUnless(
        any((candidate / "PROJECT_HANDOFF.md").is_file() for candidate in (ROOT, *ROOT.parents)),
        "project evidence is unavailable",
    )
    def test_project_nor_fixture(self):
        project = next(
            candidate for candidate in (ROOT, *ROOT.parents) if (candidate / "PROJECT_HANDOFF.md").is_file()
        )
        report = inspect_nor_file(
            project / "evidence" / "raw" / "34410a" / "firmware" / "34410A_MY47008653.BIN"
        )
        self.assertEqual(report["inputOrder"], "programmer")
        self.assertTrue(report["app"]["checksumValid"])
        self.assertTrue(report["recovery"]["checksumValid"])
        self.assertEqual(report["personalityHits"][0]["model"], "34410A")

    def test_schema45_registry_cardinality(self):
        decoded = decode_schema45_body(bytes(SCHEMA45_BODY_BYTES))
        self.assertEqual(decoded["elementCount"], 1072)
        self.assertEqual(decoded["doubleCount"], 159)
        self.assertEqual(decoded["int32Count"], 913)

    def test_cal_checksum(self):
        body = bytes(SCHEMA45_BODY_BYTES)
        checksum = (~sum(body)) & 0xFFFFFFFF
        payload = struct.pack(">HII", 45, len(body), checksum) + body
        report = parse_cal_payload(payload)
        self.assertTrue(report["checksumValid"])
        self.assertEqual(report["schema45"]["elementCount"], 1072)

    def test_forbidden_surface_absent_from_product_source(self):
        forbidden = [
            "u11" + "04",
            "tel" + "net",
            "vx" + "works",
            "gand" + "alf",
            "aapx" + "zzzzy",
            "diag:fpga:poke",
        ]
        files = list((ROOT / "utility3441x").rglob("*.py")) + [
            ROOT / "3441x_service_utility.py"
        ]
        corpus = "\n".join(path.read_text(encoding="utf-8").lower() for path in files)
        for token in forbidden:
            self.assertNotIn(token, corpus)

    def test_runtime_user_interface_is_english(self):
        files = list((ROOT / "utility3441x").rglob("*.py")) + [
            ROOT / "3441x_service_utility.py",
            ROOT / "3441x_service_utility_gui.pyw",
        ]
        corpus = "\n".join(path.read_text(encoding="utf-8") for path in files)
        self.assertNotRegex(corpus, r"[\u0400-\u04ff]")


if __name__ == "__main__":
    unittest.main()
