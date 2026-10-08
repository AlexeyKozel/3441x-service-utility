"""Tk integration checks for the read-only physical CAL history view."""
import struct
import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.cal_history import SLOT_COUNT, SLOT_SIZE, scan_cal_region
from utility3441x.cal_history_viewer import CalHistoryViewer
from utility3441x.offline import load_schema45_registry


def make_slot(state, body, *, checksum_ok=True):
    check = (~sum(body)) & 0xFFFFFFFF
    if not checksum_ok:
        check ^= 1
    header = struct.pack('>HHIII', state, 45, len(body) + 8, len(body), check)
    return (header + body).ljust(SLOT_SIZE, b'\xff')


def make_history(*, second=True):
    rows = load_schema45_registry()['registry']['rows']
    double_offset = next(row['offset'] for row in rows if row['type'] == 'double')
    int_offset = next(row['offset'] for row in rows if row['type'] == 'int32')
    old = bytearray(4924)
    new = bytearray(old)
    struct.pack_into('>d', new, double_offset, -0.0)
    struct.pack_into('>i', new, int_offset, 1)
    slots = [b'\xff' * SLOT_SIZE for _ in range(SLOT_COUNT)]
    slots[0] = make_slot(0, old)
    if second:
        slots[1] = make_slot(0xA5, new)
    slots[2] = make_slot(0xF5, old, checksum_ok=False)
    return scan_cal_region(b''.join(slots))


class CalHistoryViewerTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk display unavailable: {exc}')
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def viewer(self, history):
        view = CalHistoryViewer(self.root, 'saved_nor.bin', history)
        view.withdraw()
        self.root.update()
        self.addCleanup(view.destroy)
        return view

    def test_slots_and_raw_change_filter(self):
        view = self.viewer(make_history())
        self.assertEqual(len(view.slots_table.get_children()), 32)
        self.assertEqual(view.reference.get(), 'A1')
        self.assertEqual(view.selected.get(), 'A0')
        self.assertEqual(tuple(view.reference_box['values']), ('A0', 'A1'))
        self.assertEqual(len(view.changes_table.get_children()), 2)
        self.assertIn('2 changed / 1072 values', view.change_count.cget('text'))
        self.assertTrue(all('changed' in view.changes_table.item(iid, 'tags')
                            for iid in view.changes_table.get_children()))
        self.assertTrue(any('Bytes differ' in view.changes_table.item(iid, 'values')[3]
                            for iid in view.changes_table.get_children()))
        view.changed_only.set(False)
        view._refresh_changes()
        self.assertEqual(len(view.changes_table.get_children()), 1072)
        view.search.set('this coefficient does not exist')
        self.assertEqual(len(view.changes_table.get_children()), 0)

    def test_only_comparable_slot_opens_existing_viewer(self):
        view = self.viewer(make_history())
        view.slots_table.selection_set('A2')
        view._slot_selected()
        self.assertIn('disabled', view.open_button.state())
        with patch('utility3441x.cal_history_viewer.CalViewer') as cal_viewer:
            view._open_slot()
            cal_viewer.assert_not_called()
            view.slots_table.selection_set('A1')
            view._slot_selected()
            self.assertNotIn('disabled', view.open_button.state())
            view._open_slot()
            cal_viewer.assert_called_once()
            self.assertEqual(cal_viewer.call_args.args[2], view.by_id['A1']['report'])

    def test_one_or_zero_comparable_slots(self):
        one = self.viewer(make_history(second=False))
        self.assertEqual(one.reference.get(), 'A0')
        self.assertEqual(one.selected.get(), '')
        self.assertEqual(len(one.changes_table.get_children()), 0)
        zero = self.viewer(scan_cal_region(b'\xff' * (SLOT_COUNT * SLOT_SIZE)))
        self.assertEqual(zero.reference.get(), '')
        self.assertEqual(zero.selected.get(), '')
        self.assertEqual(len(zero.changes_table.get_children()), 0)


if __name__ == '__main__':
    unittest.main()
