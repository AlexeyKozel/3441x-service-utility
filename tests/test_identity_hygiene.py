from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.instrument import VisaInstrument, parse_idn  # noqa: E402
from utility3441x.offline import NOR_BASE  # noqa: E402


CLEAN_IDN = "Agilent Technologies,34411A,MY48005929,2.43-2.40-0.09-46-09"

# Exactly what a service backup recorded as the firmware revision, after an
# aborted batched read left its remaining values queued in the instrument and
# the next session's first query collected them.
POLLUTED_IDN = CLEAN_IDN + ";".join([""] + ["+65535"] * 32)


class IdnPollutionTests(unittest.TestCase):
    """A reply carrying another command's data must be refused, not recorded."""

    def test_a_clean_reply_parses(self):
        parsed = parse_idn(CLEAN_IDN)
        self.assertEqual(parsed["model"], "34411A")
        self.assertEqual(parsed["serial"], "MY48005929")
        self.assertEqual(parsed["firmware"], "2.43-2.40-0.09-46-09")

    def test_concatenated_response_data_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            parse_idn(POLLUTED_IDN)
        self.assertIn("output queue was not empty", str(caught.exception))

    def test_why_this_was_silent(self):
        # Guards the shape of the regression, not the fix. Splitting on commas
        # puts a comma-free tail wholly into field 3, so the old parser saw a
        # well-formed four-field reply and stored the junk as the firmware
        # revision -- which the backup manifest then hashed as good content.
        self.assertEqual(len(POLLUTED_IDN.split(",")), 4)
        self.assertTrue(POLLUTED_IDN.split(",")[3].startswith("2.43-2.40"))

    def test_a_short_reply_is_still_rejected(self):
        with self.assertRaises(ValueError):
            parse_idn("Agilent Technologies,34411A")


class DiscardPendingTests(unittest.TestCase):
    """A short PEEK reply must leave the instrument drained.

    The rest of that batch is still queued; leaving it there is what poisons
    the next reader, including a later session.
    """

    class Resource:
        def __init__(self):
            self.clears = 0

        def clear(self):
            self.clears += 1

    class ResourceThatCannotClear(Resource):
        def clear(self):
            super().clear()
            raise OSError("VI_ERROR_INV_OBJECT (-1073807346): invalid")

    def _instrument(self, resource, reply):
        instrument = VisaInstrument.__new__(VisaInstrument)
        instrument._inst = resource
        instrument.query_text = lambda _command: reply
        return instrument

    def test_short_reply_drains_before_raising(self):
        resource = self.Resource()
        instrument = self._instrument(resource, "+1;+2")
        with self.assertRaisesRegex(RuntimeError, "cardinality 2 instead of 16"):
            instrument.read_memory(NOR_BASE, 64, batch_words=16)
        self.assertEqual(resource.clears, 1)

    def test_a_failed_drain_does_not_replace_the_diagnosis(self):
        resource = self.ResourceThatCannotClear()
        instrument = self._instrument(resource, "+1;+2")
        with self.assertRaisesRegex(RuntimeError, "cardinality 2 instead of 16"):
            instrument.read_memory(NOR_BASE, 64, batch_words=16)
        self.assertEqual(resource.clears, 1)

    def test_a_good_read_never_clears(self):
        resource = self.Resource()
        instrument = self._instrument(resource, ";".join(["+0"] * 16))
        self.assertEqual(instrument.read_memory(NOR_BASE, 32, batch_words=16), bytes(32))
        self.assertEqual(resource.clears, 0)


if __name__ == "__main__":
    unittest.main()
