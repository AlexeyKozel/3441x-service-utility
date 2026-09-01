from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.flash_model import simulate_packages_on_nor  # noqa: E402
from utility3441x.identity import (  # noqa: E402
    FreshInstrumentSnapshot,
    FreshSa96Snapshot,
    build_identity_write_plan,
    build_sa96_identity_write_plan,
)
from utility3441x.offline import REC_OFFSET, detect_nor_order, inspect_nor_bytes  # noqa: E402
from utility3441x.srecord import build_xs, load_xs, parse_xs_bytes  # noqa: E402


PROJECT = next(
    (candidate for candidate in (ROOT, *ROOT.parents) if (candidate / "PROJECT_HANDOFF.md").is_file()),
    None,
)


@unittest.skipUnless(PROJECT is not None, "project evidence is unavailable")
class RealNorSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert PROJECT is not None
        cls.source_path = (
            PROJECT
            / "evidence"
            / "raw"
            / "34410a"
            / "firmware"
            / "34410A_MY47008653.BIN"
        )
        cls.stock11_path = (
            PROJECT / "evidence" / "raw" / "34411a" / "firmware" / "34411A-ch.bin"
        )
        cls.evidence = PROJECT / "derived" / "updater" / "evidence"
        cls.source_raw = cls.source_path.read_bytes()
        cls.source_cpu, cls.source_order = detect_nor_order(cls.source_raw)
        cls.control = load_xs(cls.evidence / "34410A_boot_CONTROL_SA96_updateimage.xs")
        cls.patch = load_xs(
            cls.evidence / "34410A_to_34411_personality_PATCH_SA96_updateimage.xs"
        )
        cls.app11 = load_xs(cls.evidence / "agt34411_instrument_rev243.xs")

    @staticmethod
    def _s3_image(package) -> bytes:
        return b"".join(record.data for record in package.s3_records)

    def test_control_package_is_exact_native_sa96_rewrite(self):
        self.assertEqual(
            hashlib.sha256(self.source_raw).hexdigest(),
            "626124ac53bf63305fa4989fac6f8969d20283798fd20a40da0b902201445d66",
        )
        self.assertEqual(self.source_order, "programmer")
        result = simulate_packages_on_nor(
            self.source_raw, [self.control], source=str(self.source_path)
        )
        self.assertEqual(result.cpu_before, result.cpu_after)
        self.assertEqual(result.report["steps"][0]["changedBytes"], 0)
        self.assertEqual(result.report["ignoredTrailingBytes"], 256)

    def test_identity_builder_matches_preserved_patch_vector(self):
        source_report = inspect_nor_bytes(self.source_cpu)
        recovery_length = int(source_report["recovery"]["length"])
        recovery = self.source_cpu[REC_OFFSET : REC_OFFSET + recovery_length]
        snapshot = FreshInstrumentSnapshot(
            session_id="offline-real-nor-fixture",
            resource="FILE-FIXTURE",
            idn="Agilent Technologies,34410A,MY47008653,2.43",
            serial="MY47008653",
            current_model="34410A",
            app_revision="2.43",
            recovery_revision="2.35",
            recovery=recovery,
            captured_at_utc="2026-08-31T00:00:00Z",
        )
        plan = build_identity_write_plan(snapshot, "34411A")
        fast_plan = build_sa96_identity_write_plan(
            FreshSa96Snapshot(
                session_id="offline-real-nor-fixture",
                resource="FILE-FIXTURE",
                idn="Agilent Technologies,34410A,MY47008653,2.43",
                serial="MY47008653",
                current_model="34410A",
                app_revision="2.43",
                recovery_revision="2.35",
                sa96=self.source_cpu[REC_OFFSET : REC_OFFSET + 0x10000],
                captured_at_utc="2026-08-31T00:00:00Z",
            ),
            "34411A",
        )
        control_data = self._s3_image(self.control)
        patch_data = self._s3_image(self.patch)
        # Native packages intentionally do not transfer reserved bytes SA96+0x08..0x0F.
        self.assertEqual(plan.source_sa96[:8] + plan.source_sa96[16:], control_data)
        self.assertEqual(plan.target_sa96[:8] + plan.target_sa96[16:], patch_data)
        self.assertEqual(plan.changed_recovery_offsets, (2, 3, 0x230E, 0x230F))
        self.assertEqual(fast_plan.target_sa96, plan.target_sa96)
        self.assertEqual(fast_plan.package_bytes, plan.package_bytes)
        self.assertEqual(
            hashlib.sha256(plan.target_sa96).hexdigest(),
            "5c947f337595ff097ea198b2c25772ef799bd86a010d8ed86a7639f3e50b052b",
        )

    def test_patch_then_official_app_produces_consistent_34411_state(self):
        result = simulate_packages_on_nor(
            self.source_raw,
            [self.patch, self.app11],
            source=str(self.source_path),
        )
        report = result.report
        self.assertEqual([step["changedBytes"] for step in report["steps"]], [4, 3445642])
        self.assertEqual(report["steps"][0]["modelAfter"], "34411A")
        self.assertEqual(report["steps"][1]["modelBefore"], "34411A")
        self.assertEqual(report["totalChangedBytes"], 3445646)
        self.assertEqual(
            report["resultCpuSha256"],
            "fe560f52e09cc96304fd3850dcd71c715dc320e9065cb810cd39970350a9ee74",
        )
        after = report["after"]
        self.assertTrue(after["app"]["checksumValid"])
        self.assertTrue(after["recovery"]["checksumValid"])
        self.assertEqual(after["embeddedApp"]["model"], "34411A")
        self.assertEqual(after["embeddedApp"]["revision"], "2.43")
        self.assertEqual(after["personalityHits"][0]["model"], "34411A")

        stock11_cpu, _ = detect_nor_order(self.stock11_path.read_bytes())
        stock11_report = inspect_nor_bytes(stock11_cpu)
        logical_app_length = int(after["app"]["length"])
        self.assertEqual(
            result.cpu_after[:logical_app_length], stock11_cpu[:logical_app_length]
        )
        self.assertEqual(after["app"]["sha256Logical"], stock11_report["app"]["sha256Logical"])
        # PATCH changes the boot identity without replacing the complete embedded Recovery image.
        self.assertEqual(after["embeddedRecovery"]["model"], "34410A")

    def test_official_34411_app_is_rejected_before_identity_switch(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            simulate_packages_on_nor(self.source_raw, [self.app11])

    def test_out_of_window_s3_is_rejected(self):
        raw = build_xs(
            model="34410A",
            image_type="instrumentimage",
            image_revision="test",
            description="Out of window fixture",
            s3_records=[(0xFFE00000, bytes(16))],
        )
        with self.assertRaisesRegex(ValueError, "outside"):
            simulate_packages_on_nor(self.source_raw, [parse_xs_bytes(raw)])


if __name__ == "__main__":
    unittest.main()
