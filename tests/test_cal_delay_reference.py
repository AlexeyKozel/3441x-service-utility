"""Check bundled table bytes against the APP11 extraction receipts."""
import hashlib
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utility3441x.cal_delay_reference import load_reference


class DelayReferenceTests(unittest.TestCase):
    def test_table_bytes_match_firmware(self):
        data = load_reference()
        expected = {'mc': '498aeac0611afe5b465220f47ad1a56302e5a846e1f3f388e9ef3ee198f14a53',
                    'mz': 'b1e38b7c380d3bc6249a5544f80997d2ac66707d5816d204e6fe0b4c510c7a69'}
        for key, digest in expected.items():
            words = [x for page in data['pages'] for row in page[key] for x in row]
            self.assertEqual(len(words), 320)
            self.assertEqual(hashlib.sha256(struct.pack('>320I', *words)).hexdigest(), digest)
        self.assertEqual(data['nplc'], [.001, .002, .006, .02, .06, .2, 1, 2, 10, 100])
        self.assertEqual([len(p['ranges']) for p in data['pages']], [5, 6, 8, 8])
