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
from utility3441x.cal_guide import topic_for, linked_indices
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

    def test_guide_navigation_preserves_adc_profile_and_opens_filtered_row(self):
        v = self.viewer
        v.search.set('Adc_DcOffset[ACV]')
        v.tabs.select(v.guide)
        self.root.update()
        self.assertEqual(v.tabs.select(), str(v.guide))
        self.assertEqual(v.guide.topic, 'adc')
        links = v.guide.table.get_children()
        self.assertEqual(len(links), 8)
        self.assertTrue(all(v.rows[int(i)]['meaning']['groupId'] == 1 for i in links))
        target = next(i for i in links if v.rows[int(i)]['meaning']['family'] == 'Adc_LutGain')
        v.guide.table.selection_set(target)
        v.guide.open_selected()
        self.assertEqual(v.table.selection(), (target,))
        self.assertEqual(v.search.get(), '')
        self.assertEqual(v.family.get(), 'All')
        self.assertTrue(v.lifecycle.get())
        self.assertEqual(v.tabs.select(), str(v.values_tab))
        v.tabs.select(v.guide)
        self.root.update()
        self.assertEqual(v.guide.context.cget('text'), 'ADC profile: ACV')

    def test_guide_dcv_links_and_general_page(self):
        v = self.viewer
        v.search.set('AdcQuad')
        v.tabs.select(v.guide)
        self.root.update()
        self.assertEqual(v.guide.topic, 'dcv')
        self.assertEqual(len(v.guide.table.get_children()), 16)
        self.assertIn('V = V0', v.guide.text.get('1.0', 'end'))
        v.guide.show('storage')
        self.assertEqual(v.guide.table.get_children(), ())
        self.assertIn('disabled', v.guide.open_button.state())
        v.guide.open_selected()
        self.assertEqual(v.tabs.select(), str(v.guide))

    def test_reference_covers_families_and_groups_filter_links(self):
        v = self.viewer
        self.assertTrue(all(topic_for(row) != 'storage' for row in v.rows))
        for name, topic in [('Divider10M', 'res'), ('CapOffset', 'freq_cap'),
                            ('HeaterGain', 'drive'), ('McDelay', 'timing'),
                            ('DciGain', 'dci'), ('AcvGain', 'ac')]:
            v.search.set(name)
            v.tabs.select(v.guide)
            self.root.update()
            self.assertEqual(v.guide.topic, topic)
            expected = set(linked_indices(v.rows, topic))
            shown = {int(i) for i in v.guide.table.get_children()}
            self.assertTrue(shown <= expected)
            if topic != 'ac':
                self.assertEqual(shown, expected)
            v.tabs.select(v.values_tab)
            self.root.update()
        v.guide.show('ac')
        filter_links = [i for i in v.guide.table.get_children()
                        if v.rows[int(i)]['meaning']['family'] in ('flatness', 'lp')]
        self.assertEqual(len(filter_links), 13)
        target = filter_links[0]
        v.guide.table.selection_set(target)
        v.guide.open_selected()
        self.assertEqual(v.table.selection(), (target,))
        self.assertTrue(v.table.item(v.table.parent(target), 'open'))

    def test_plot_modes_and_invalid_frequency(self):
        v = self.viewer
        self.assertEqual(len(v.vectors), 13)
        self.assertIn('cycles per coefficient-index step', v.max_x_label.cget('text'))
        v.max_x.set('10000')
        v._draw()
        self.assertTrue(any('coefficient-index step span' in v.canvas.itemcget(item, 'text')
                            for item in v.canvas.find_all() if v.canvas.type(item) == 'text'))
        v.vector.set('Acv100mVFlatnessCoefs')
        v.mode.set('APP11 2.43 image1 cascade (nominal Hz)')
        self.assertEqual(len(v.curve), 4097)
        self.assertIn('frequency in Hz', v.max_x_label.cget('text'))
        self.assertIn('72 G3/event', v.scope.cget('text'))
        v.max_x.set('100000')
        v._draw()
        self.assertTrue(v.canvas.find_withtag('response'))
        v.vector.set('Aci100uAFlatnessCoefs')
        self.assertIn('108 G3/event', v.scope.cget('text'))
        v.max_x.set('nan')
        v._draw()
        self.assertFalse(v.canvas.find_withtag('response'))
        self.assertTrue(any('full Hz span' in v.canvas.itemcget(item, 'text')
                            for item in v.canvas.find_all() if v.canvas.type(item) == 'text'))
        v.vector.set('AcvLpFilter')
        self.assertEqual(v.curve, [])
        v.mode.set('Coefficient index')
        self.assertEqual(len(v.curve), 2049)

    def test_calculation_and_use_is_optional_and_family_specific(self):
        v = self.viewer
        v.search.set('DcvGain10')
        self.assertNotIn('How it is used', v.detail.get('1.0', 'end'))
        v.lifecycle.set(True)
        v._select()
        details = v.detail.get('1.0', 'end')
        self.assertIn('How it is used', details)
        self.assertIn('g = G / T', details)
        self.assertIn('AdcQuad', details)
        self.assertNotIn('getCalCoeffs @', details)
        v.technical.set(True)
        v._select()
        self.assertIn('getCalCoeffs @0x314FE8', v.detail.get('1.0', 'end'))
        v.search.set('HeaterGain')
        details = v.detail.get('1.0', 'end')
        self.assertIn('divides by HeaterGain', details)
        self.assertNotIn('g = G / T', details)
        self.assertNotIn('no detailed card', details)

    def test_adc_lifecycle_hides_research_details_by_default(self):
        v = self.viewer
        v.search.set('Adc_LutGain[DCV]')
        v.lifecycle.set(True)
        v._select()
        detail = v.detail.get('1.0', 'end')
        self.assertIn('feedbackLutGainTune', detail)
        self.assertIn('0x0100', detail)
        self.assertNotIn('Evidence:', detail)
        self.assertNotIn('research/', detail)
        v.technical.set(True)
        v._select()
        self.assertIn('calculateRegValues @0x26446C', v.detail.get('1.0', 'end'))

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
