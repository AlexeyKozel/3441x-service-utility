"""Journal framing and exact changes, independent of GUI display formatting."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utility3441x.cal_history import scan_cal_region, scan_cal_history, compare_slots, SLOT_SIZE


def slot(state=0xA5, body=None, version=45, corrupt=False):
    body = bytes(4924) if body is None else body
    check = ((~sum(body)) & 0xffffffff) ^ int(corrupt)
    return (struct.pack('>HHIII', state, version, len(body)+8, len(body), check)
            + body).ljust(SLOT_SIZE, b'\xff')


def history(*slots):
    return scan_cal_region(b''.join(slots).ljust(32*SLOT_SIZE, b'\xff'))


class CalHistoryTests(unittest.TestCase):
    def test_state_integrity_schema_and_duplicates_are_separate(self):
        h = history(slot(0), slot(0xA5), slot(0xA0), slot(0xF5),
                    slot(0xA5, corrupt=True), slot(0, version=44), slot(0x1234))
        self.assertEqual(len(h['slots']), 32)
        self.assertIsNone(h['currentSlot'])  # conflicting marker, even though one is corrupt
        a = h['slots']
        self.assertEqual(a[0]['status'], 'Historical (retired)')
        self.assertEqual(a[1]['duplicateOf'], 'A0')
        self.assertTrue(a[2]['comparable'])
        for n in (3, 4, 5, 6):
            self.assertFalse(a[n]['comparable'])
            self.assertIsNone(a[n]['report'])
        self.assertEqual(a[4]['status'], 'Invalid')
        self.assertEqual(a[7]['status'], 'Empty')
        self.assertEqual(a[-1]['id'], 'B15')

    def test_current_marker_and_fallback_do_not_invent_live_state(self):
        self.assertEqual(history(slot(0), slot(0xA5))['currentSlot'], 'A1')
        fallback = history(slot(0xA0))
        self.assertIsNone(fallback['currentSlot'])
        self.assertEqual(fallback['slots'][0]['status'], 'Fallback')
        self.assertIn('unresolved', fallback['selectionNote'])

    def test_bad_lengths_and_partial_erased_slot_do_not_cross_boundaries(self):
        bad = bytearray(slot())
        struct.pack_into('>II', bad, 4, 0xfffffff8, 0xfffffff0)
        partial = bytearray(b'\xff'*SLOT_SIZE); partial[-1] = 0
        h = history(bytes(bad), bytes(partial), slot())
        self.assertEqual(h['slots'][0]['status'], 'Invalid')
        self.assertEqual(h['slots'][1]['status'], 'Incomplete')
        self.assertEqual(h['currentSlot'], None)  # another invalid current marker
        self.assertTrue(h['slots'][2]['comparable'])
        with self.assertRaises(ValueError): scan_cal_region(b'')
        with self.assertRaises(ValueError): scan_cal_history(bytes(4934))

    def test_byte_exact_zero_nan_and_finite_difference(self):
        old, new = bytearray(4924), bytearray(4924)
        old[8:16] = bytes.fromhex('7ff8000000000001')
        new[8:16] = bytes.fromhex('7ff8000000000002')
        struct.pack_into('>d', new, 0, -0.0)
        struct.pack_into('>d', old, 16, 1.0)
        struct.pack_into('>d', new, 16, 1.25)
        h = history(slot(0, old), slot(0xA5, new))
        a,b = h['slots'][:2]
        rows = compare_slots(a,b)
        self.assertEqual(len(rows), 1072)
        changed = [x for x in rows if x['changed']]
        self.assertEqual([x['offset'] for x in changed], [0,8,16])
        self.assertIn('Bytes differ', changed[0]['delta'])
        self.assertIn('Non-finite', changed[1]['delta'])
        self.assertEqual(changed[2]['delta'], '0.25')
        self.assertFalse(any(x['changed'] for x in compare_slots(a,a)))
        with self.assertRaises(ValueError): compare_slots(a,h['slots'][2])


if __name__ == '__main__':
    unittest.main()
