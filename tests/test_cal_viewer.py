"""Tk widget integration checks for human-readable CAL inspection."""
import struct
import sys
import tkinter as tk
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utility3441x.cal_viewer import CalViewer
from utility3441x.offline import load_schema45_registry, parse_cal_payload


class CalViewerTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk display unavailable: {exc}')
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        body = bytearray(4924)
        for row in load_schema45_registry()['registry']['rows']:
            if row['type'] == 'int32':
                struct.pack_into('>i', body, row['offset'], 1)
        payload = struct.pack('>HII', 45, len(body), (~sum(body)) & 0xffffffff) + body
        report = parse_cal_payload(payload, explain=True)
        self.viewer = CalViewer(self.root, 'test_cal.bin', report)
        self.viewer.withdraw()
        self.root.update()

    def test_search_family_and_usage_details(self):
        v = self.viewer
        self.assertEqual(len(v.table.get_children()), 175)
        self.assertEqual(sum(len(v.table.get_children(g)) for g in v.filter_groups), 910)
        v.search.set('HeaterGain')
        self.assertEqual(len(v.table.get_children()), 1)
        self.assertNotIn('Source:', v.detail.get('1.0', 'end'))
        self.assertNotIn('body offset', v.detail.get('1.0', 'end'))
        v.technical.set(True)
        v._select()
        self.assertIn('divides', v.detail.get('1.0', 'end'))
        self.assertIn('Source:', v.detail.get('1.0', 'end'))
        v.search.set('')
        v.family.set('McDelay')
        self.assertIn('OPEN', v.detail.get('1.0', 'end'))
        v.search.set('no such coefficient')
        self.assertEqual(len(v.table.get_children()), 0)
        self.assertIn('No matching', v.detail.get('1.0', 'end'))

    def test_plot_modes_and_invalid_frequency(self):
        v = self.viewer
        self.assertEqual(len(v.vectors), 13)
        v.vector.set('Acv100mVFlatnessCoefs')
        v.mode.set('APP11 2.43 image1 cascade (nominal Hz)')
        self.assertEqual(len(v.curve), 4097)
        self.assertIn('72 G3/event', v.scope.cget('text'))
        v.max_x.set('100000')
        v._draw()
        self.assertTrue(v.canvas.find_withtag('response'))
        v.vector.set('Aci100uAFlatnessCoefs')
        self.assertIn('108 G3/event', v.scope.cget('text'))
        v.max_x.set('nan')
        v._draw()
        self.assertFalse(v.canvas.find_withtag('response'))
        v.vector.set('AcvLpFilter')
        self.assertEqual(v.curve, [])
        v.mode.set('Coefficient index')
        self.assertEqual(len(v.curve), 2049)

    def test_delay_reference_from_both_cal_fields(self):
        v = self.viewer
        for name in ('McDelay', 'MzDelay'):
            v.search.set(name)
            self.assertEqual(v.delay_reference_button.winfo_manager(), 'pack')
            self.assertIn('separate from the saved CAL', v.detail.get('1.0', 'end'))
            ranges = v.detail.tag_ranges('delay_reference')
            self.assertEqual(len(ranges), 2)
            self.assertEqual(v.detail.get(*ranges), 'Open delay reference…')
            self.assertEqual(str(ranges[0]), '4.0')
            self.assertEqual(v.detail.yview()[0], 0.0)
        # Exercise the link through Tk's tag event dispatch, including disabled Text.
        v.deiconify()
        self.root.update()
        box = v.detail.bbox('4.0')
        self.assertIsNotNone(box)
        with patch.object(v, '_open_delay_reference') as open_reference:
            v.detail.event_generate('<Motion>', x=box[0]+2, y=box[1]+2)
            self.root.update()
            v.detail.event_generate('<Button-1>', x=box[0]+2, y=box[1]+2)
            self.root.update()
            open_reference.assert_called_once_with()
        v.withdraw()
        ref = v._open_delay_reference()
        self.addCleanup(ref.destroy)
        ref.withdraw()
        ref.mode.set('Resistance 2-wire')
        ref.nplc.set('1')
        values = [ref.table.item(x, 'values') for x in ref.table.get_children()]
        self.assertEqual(values[2], ('1', '10 kohm', '25', '0.498824', '10', '0.199529'))
        ref.mode.set('Resistance 4-wire')
        self.assertIn('not been confirmed', ref.note.cget('text'))
        ref.nplc.set('All')
        self.assertEqual(len(ref.table.get_children()), 80)
        v.search.set('HeaterGain')
        self.assertEqual(v.delay_reference_button.winfo_manager(), '')
        self.assertEqual(v.detail.tag_ranges('delay_reference'), ())
        v.search.set('no such coefficient')
        self.assertEqual(v.delay_reference_button.winfo_manager(), '')

    def test_default_view_keeps_research_details_hidden(self):
        v = self.viewer
        v.search.set('Adc_DcOffset[DCV]')
        self.assertEqual(len(v.table.get_children()), 1)
        detail = v.detail.get('1.0', 'end')
        for internal in ('Source:', 'body offset', 'SHA-256', 'Usage evidence:'):
            self.assertNotIn(internal, detail)
        self.assertIn('D+P', detail)
        self.assertNotIn('physical equivalent not established', detail.lower())
        self.assertEqual(tuple(v.table['columns']), ('name', 'value', 'note'))

    def test_filter_groups_expand_search_and_keep_leaf_details(self):
        v = self.viewer
        self.assertEqual(len(v.filter_groups), 13)
        group = next(iter(v.filter_groups))
        self.assertFalse(v.table.item(group, 'open'))
        v.deiconify()
        v.table.see(group)
        self.root.update()
        x, y, width, height = v.table.bbox(group, '#0')
        v.table.event_generate('<Button-1>', x=x+80, y=y+height//2)
        self.root.update()
        self.assertTrue(v.table.item(group, 'open'))
        child = v.table.get_children(group)[0]
        v.table.selection_set(child)
        v._select()
        self.assertIn(v.display_rows[int(child)]['title'], v.detail.get('1.0', 'end'))
        v.search.set('Acv100mVFlatnessCoefs[69]')
        self.assertEqual(len(v.filter_groups), 1)
        group = next(iter(v.filter_groups))
        self.assertTrue(v.table.item(group, 'open'))
        self.assertEqual(len(v.table.get_children(group)), 1)
        self.assertEqual(v.count.cget('text'), '1 / 1072 values')
        v.search.set('')
        self.assertTrue(all(not v.table.item(g, 'open') for g in v.filter_groups))


if __name__ == '__main__':
    unittest.main()
