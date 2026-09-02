from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.identity import (  # noqa: E402
    FreshSa96Snapshot,
    IdentityWritePlan,
    SA96_SIZE,
    assert_package_matches_plan,
)


def minimal_plan(package_bytes: bytes) -> IdentityWritePlan:
    snapshot = FreshSa96Snapshot(
        session_id="session",
        resource="TCPIP0::198.51.100.7::inst0::INSTR",
        idn="Agilent Technologies,34410A,MY00000001,2.43-2.40-0.09-46-09",
        serial="MY00000001",
        current_model="34410A",
        app_revision="2.43-2.40-0.09-46-09",
        sa96=bytes(SA96_SIZE),
        captured_at_utc="2026-01-01T00:00:00Z",
    )
    return IdentityWritePlan(
        snapshot=snapshot,
        target_model="34411A",
        source_personality=0x235A,
        target_personality=0xB643,
        source_sa96=bytes(SA96_SIZE),
        target_sa96=bytes(SA96_SIZE),
        source_recovery_sha256=None,
        target_recovery_sha256=None,
        package_bytes=package_bytes,
        changed_recovery_offsets=(0, 1, 2, 3),
        checksum_policy="stored-recovery-sum32-word-delta",
        full_recovery_checksum_verified=False,
    )


class PlanBindingTests(unittest.TestCase):
    """The uploaded bytes must be the bytes whose hash the operator approved."""

    def test_matching_package_is_accepted(self):
        plan = minimal_plan(b"%headerlength=9\r\nS9030000FC\r\n")
        assert_package_matches_plan(plan, plan.package_bytes)

    def test_tampered_package_is_rejected(self):
        plan = minimal_plan(b"%headerlength=9\r\nS9030000FC\r\n")
        with self.assertRaises(RuntimeError) as caught:
            assert_package_matches_plan(plan, plan.package_bytes + b"\r\n")
        self.assertIn("does not match the approved write plan", str(caught.exception))

    def test_created_at_is_stamped_once_and_is_stable(self):
        plan = minimal_plan(b"payload")
        self.assertEqual(plan.as_dict()["createdAtUtc"], plan.created_at_utc)
        self.assertEqual(
            plan.as_dict()["createdAtUtc"], plan.as_dict()["createdAtUtc"]
        )


class WritePathSourceTests(unittest.TestCase):
    """Both write front ends must apply the same guards, in the same order."""

    def test_both_front_ends_bind_the_package_to_the_plan(self):
        for name in ("cli.py", "gui.py"):
            source = (ROOT / "utility3441x" / name).read_text(encoding="utf-8")
            with self.subTest(front_end=name):
                readback = source.index("assert_fresh_readback_before_write(plan")
                upload = source.index("execute_update(", readback)
                self.assertIn(
                    "assert_package_matches_plan(plan, package.raw)",
                    source[readback:upload],
                    "the binding must sit between the fresh read-back and the "
                    "upload it guards",
                )

    def test_write_paths_use_the_named_sa96_constants(self):
        for name in ("cli.py", "gui.py"):
            source = (ROOT / "utility3441x" / name).read_text(encoding="utf-8")
            with self.subTest(front_end=name):
                self.assertNotIn("0xFFE00000", source)
                self.assertNotIn("0x10000,", source)


class GuiResilienceTests(unittest.TestCase):
    """Source-level checks; the Tk event loop is not started under test."""

    def setUp(self):
        self.source = (ROOT / "utility3441x" / "gui.py").read_text(encoding="utf-8")

    def test_drain_reschedules_even_when_a_handler_raises(self):
        drain = self.source[self.source.index("def _drain"):]
        drain = drain[: drain.index("def _progress_callback")]
        self.assertIn("finally:", drain)
        self.assertIn("traceback.print_exc()", drain)
        self.assertLess(
            drain.index("finally:"),
            drain.index("self.after(100, self._drain)"),
            "the reschedule must be in the finally block",
        )

    def test_closing_the_window_while_busy_is_confirmed(self):
        self.assertIn('self.protocol("WM_DELETE_WINDOW", self._on_close)', self.source)
        self.assertIn("def _on_close", self.source)
        handler = self.source[self.source.index("def _on_close"):]
        handler = handler[: handler.index("def _build")]
        self.assertIn("self._busy and not messagebox.askyesno", handler)
        self.assertIn('default="no"', handler)
        self.assertIn("self.destroy()", handler)


if __name__ == "__main__":
    unittest.main()
