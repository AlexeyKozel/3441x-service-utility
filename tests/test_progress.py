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


if __name__ == "__main__":
    unittest.main()
