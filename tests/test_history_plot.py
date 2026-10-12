"""Focused tests for CAL history trend math and interpreted field selection."""
import math
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.cal_history import SLOT_COUNT, SLOT_SIZE, scan_cal_region
from utility3441x.cal_history_plot import calculate_trend, coefficient_choices
from utility3441x.offline import load_schema45_registry


REGISTRY_ROWS = load_schema45_registry()['registry']['rows']
GAIN = next(row for row in REGISTRY_ROWS if row['name'] == 'DcvGain10')
DIVIDER = next(row for row in REGISTRY_ROWS if row['name'] == 'Divider10M')


def make_record(state, values):
    body = bytearray(4924)
    for row, value in values.items():
        spec = next(item for item in REGISTRY_ROWS if item['name'] == row)
        if spec['type'] == 'double':
            struct.pack_into('>d', body, spec['offset'], value)
        else:
            struct.pack_into('>i', body, spec['offset'], value)
    checksum = (~sum(body)) & 0xffffffff
    header = struct.pack('>HHIII', state, 45, len(body) + 8, len(body), checksum)
    return (header + body).ljust(SLOT_SIZE, b'\xff')


def make_history(reference_gain=2.0):
    slots = [b'\xff' * SLOT_SIZE for _ in range(SLOT_COUNT)]
    slots[0] = make_record(0, {'DcvGain10': reference_gain, 'Divider10M': 10_000_000.0})
    invalid = bytearray(make_record(0xF5, {'DcvGain10': 99.0, 'Divider10M': 99.0}))
    invalid[15] ^= 1
    slots[1] = bytes(invalid)
    slots[2] = make_record(0xA5, {'DcvGain10': 2.000002, 'Divider10M': 10_000_002.0})
    slots[3] = make_record(0, {'DcvGain10': math.nan, 'Divider10M': 10_000_003.0})
    return scan_cal_region(b''.join(slots))


class HistoryPlotTests(unittest.TestCase):
    def test_choices_use_interpreted_titles_and_raw_names(self):
        choices = coefficient_choices(make_history())
        by_name = {choice['name']: choice for choice in choices}
        self.assertEqual(by_name['DcvGain10']['mode'], 'ppm')
        self.assertIn('DC voltage scale', by_name['DcvGain10']['label'])
        self.assertEqual(by_name['Divider10M']['mode'], 'ohm_delta')
        self.assertIn('[Divider10M]', by_name['Divider10M']['label'])

    def test_relative_ppm_and_physical_gaps(self):
        trend = calculate_trend(make_history(), 'DcvGain10', 'A0')
        self.assertTrue(trend['available'])
        self.assertEqual(trend['unit'], 'ppm')
        self.assertEqual([point['index'] for point in trend['points']], [0, 2])
        self.assertAlmostEqual(trend['points'][0]['y'], 0.0)
        self.assertAlmostEqual(trend['points'][1]['y'], 1.0)

    def test_divider_is_absolute_ohm_delta(self):
        trend = calculate_trend(make_history(), 'Divider10M', 'A0')
        self.assertTrue(trend['available'])
        self.assertEqual(trend['unit'], 'ohm')
        self.assertEqual([point['index'] for point in trend['points']], [0, 2, 3])
        self.assertAlmostEqual(trend['points'][1]['y'], 2.0)

    def test_zero_or_nonfinite_reference_is_unavailable(self):
        zero = calculate_trend(make_history(reference_gain=0.0), 'DcvGain10', 'A0')
        self.assertFalse(zero['available'])
        self.assertIn('zero', zero['reason'])
        invalid = calculate_trend(make_history(), 'DcvGain10', 'A3')
        self.assertFalse(invalid['available'])
        self.assertIn('non-finite', invalid['reason'])

    def test_missing_or_invalid_reference_slot_is_unavailable(self):
        missing = calculate_trend(make_history(), 'DcvGain10', 'A1')
        self.assertFalse(missing['available'])
        self.assertIn('valid decoded CAL', missing['reason'])
        self.assertFalse(calculate_trend(make_history(), 'DcvGain10', 'no-slot')['available'])


if __name__ == '__main__':
    unittest.main()
