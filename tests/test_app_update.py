from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.app_update import wait_for_final_app_identity  # noqa: E402
from utility3441x.srecord import build_xs, parse_xs_bytes  # noqa: E402


def app_package():
    return parse_xs_bytes(
        build_xs(
            model="34411A",
            image_type="instrumentimage",
            image_revision="2.43",
            description="Synthetic APP",
            s3_records=[(0xFF880000, bytes(16))],
        )
    )


class AppCompletionTests(unittest.TestCase):
    def test_waits_through_old_identity_and_disconnect(self):
        class Instrument:
            def __init__(self):
                self.identities = [
                    {"model": "34410A", "serial": "MY00000001"},
                    TimeoutError("internal APP programming"),
                    {"model": "34411A", "serial": "MY00000001"},
                ]
                self.reconnects = 0

            def identity(self):
                value = self.identities.pop(0)
                if isinstance(value, Exception):
                    raise value
                return value

            def reconnect(self):
                self.reconnects += 1

        instrument = Instrument()
        messages: list[str] = []
        after = wait_for_final_app_identity(
            instrument,
            app_package(),
            {"model": "34410A", "serial": "MY00000001"},
            sleep=lambda _: None,
            status=messages.append,
        )
        self.assertEqual(after["model"], "34411A")
        self.assertEqual(instrument.reconnects, 2)
        self.assertEqual(len(messages), 2)

    def test_timeout_never_repeats_upload(self):
        class Clock:
            value = 0.0

            def monotonic(self):
                return self.value

            def sleep(self, seconds):
                self.value += seconds

        class Instrument:
            reconnects = 0

            def identity(self):
                return {"model": "34410A", "serial": "MY00000001"}

            def reconnect(self):
                self.reconnects += 1

        clock = Clock()
        instrument = Instrument()
        with self.assertRaisesRegex(TimeoutError, "do not retry automatically"):
            wait_for_final_app_identity(
                instrument,
                app_package(),
                {"model": "34410A", "serial": "MY00000001"},
                timeout_seconds=5,
                poll_seconds=2,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
        self.assertGreaterEqual(instrument.reconnects, 2)


if __name__ == "__main__":
    unittest.main()
