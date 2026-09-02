from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.instrument import VisaInstrument  # noqa: E402
from utility3441x.offline import NOR_BASE  # noqa: E402


class ProgressTests(unittest.TestCase):
    def test_gui_report_has_vertical_and_horizontal_scrollbars(self):
        source = (ROOT / "utility3441x" / "gui.py").read_text(encoding="utf-8")
        self.assertIn('orient="vertical", command=self.output.yview', source)
        self.assertIn('orient="horizontal", command=self.output.xview', source)
        self.assertIn("yscrollcommand=output_scroll_y.set", source)
        self.assertIn("xscrollcommand=output_scroll_x.set", source)
        self.assertIn('"warning", foreground="#B00020"', source)
        self.assertIn('self.events.put(("warning", result["warning"]))', source)

    def test_read_memory_reports_monotonic_byte_progress(self):
        class FakeInstrument:
            @staticmethod
            def query_text(command: str) -> str:
                count = command.count("PEEK?")
                return ";".join("0" for _ in range(count))

        events = []
        payload = VisaInstrument.read_memory(
            FakeInstrument(),
            NOR_BASE,
            512,
            batch_words=16,
            progress=lambda completed, total: events.append((completed, total)),
        )
        self.assertEqual(payload, bytes(512))
        self.assertGreater(len(events), 1)
        self.assertEqual(events[-1], (512, 512))
        self.assertEqual(events, sorted(events))

    def test_updater_exchange_matches_single_bounded_factory_read(self):
        class VisaLibrary:
            def __init__(self):
                self.reads = []

            def read(self, session, size):
                self.reads.append((session, size))
                return b"0\n", object()

        class Resource:
            def __init__(self):
                self.timeout = 30_000
                self.session = 123
                self.visalib = VisaLibrary()
                self.writes = []

            def write_raw(self, payload):
                self.writes.append(payload)
                return len(payload)

            def read_raw(self):
                raise AssertionError("exchange_raw must not use PyVISA read_raw")

        instrument = object.__new__(VisaInstrument)
        instrument._inst = Resource()
        instrument._factory_block_timeout_active = False

        self.assertEqual(instrument.exchange_raw(b"frame\n"), "0")
        self.assertEqual(instrument._inst.timeout, 5_000)
        self.assertEqual(instrument._inst.visalib.reads, [(123, 100)])
        self.assertEqual(instrument._inst.writes, [b"frame\n"])

        self.assertEqual(instrument.exchange_raw(b"next\n"), "0")
        self.assertEqual(
            instrument._inst.visalib.reads,
            [(123, 100), (123, 100)],
        )

    def test_updater_short_write_is_not_read_or_retried(self):
        class VisaLibrary:
            reads = 0

            def read(self, session, size):
                self.reads += 1
                return b"0\n", object()

        class Resource:
            timeout = 30_000
            session = 123
            visalib = VisaLibrary()

            @staticmethod
            def write_raw(payload):
                return len(payload) - 1

        instrument = object.__new__(VisaInstrument)
        instrument._inst = Resource()
        instrument._factory_block_timeout_active = False

        with self.assertRaisesRegex(RuntimeError, "ambiguous short write"):
            instrument.exchange_raw(b"frame\n")
        self.assertEqual(instrument._inst.visalib.reads, 0)


if __name__ == "__main__":
    unittest.main()
