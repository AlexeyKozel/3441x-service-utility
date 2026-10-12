"""Numerical and widget checks for approved CAL plots."""
import cmath
import math
from pathlib import Path
import struct
import sys
import tkinter as tk
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from utility3441x.cal_filters import impulse_response, cascade_impulse_response, cascade_response
from utility3441x.cal_quad_viewer import quadratic_curve
from utility3441x.cal_viewer import CalViewer
from utility3441x.cal_history_viewer import CalHistoryViewer
from utility3441x.offline import parse_cal_payload, load_schema45_registry
from test_history_plot import make_history


def report(q=5e-8):
    body=bytearray(4924)
    for row in load_schema45_registry()['registry']['rows']:
        if row['type']=='int32':
            struct.pack_into('>i',body,row['offset'],1)
        if row['name']=='AdcQuad':
            struct.pack_into('>d',body,row['offset'],q)
    return parse_cal_payload(struct.pack('>HII',45,len(body),(~sum(body))&0xffffffff)+body,explain=True)


class PlotMathTests(unittest.TestCase):
    def test_quadratic_polarities_zero_and_negative(self):
        pts=quadratic_curve(report())
        self.assertAlmostEqual(pts[0][1],5)
        self.assertAlmostEqual(pts[-1][1],5)
        self.assertEqual(pts[200],(0,0))
        self.assertEqual(quadratic_curve(report(0))[-1][1],0)
        self.assertAlmostEqual(quadratic_curve(report(-5e-8))[-1][1],-5)

    def test_quadratic_rejects_bad_inputs(self):
        for q in (math.nan,math.inf,1e308):
            with self.assertRaises(ValueError):quadratic_curve(report(q))
        bad=report();bad['checksumValid']=False
        with self.assertRaises(ValueError):quadratic_curve(bad)
        for span in (0,-1,11,math.nan):
            with self.assertRaises(ValueError):quadratic_curve(report(),span)

    def test_impulse_cascade_matches_frequency_operator(self):
        flat=[1,3,-1,2];lp=[2,1,2]
        for kind in ('acv','aci'):
            impulse=cascade_impulse_response(flat,lp,kind)
            self.assertAlmostEqual(sum(y for _,y in impulse),1)
            self.assertEqual(len(impulse),3*(2 if kind=='acv' else 7)+3)
            for f,db in cascade_response(flat,lp,kind,points=23):
                h=sum(y*cmath.exp(-2j*math.pi*f*t*1e-6) for t,y in impulse)
                self.assertAlmostEqual(20*math.log10(abs(h)),db,places=9)

    def test_single_impulse_and_invalid_normalization(self):
        self.assertEqual(impulse_response([1,2,1]),[(0.,.25),(1.,.5),(2.,.25)])
        for taps in ([1,-1],[],[math.nan],[math.inf]):
            with self.assertRaises(ValueError):impulse_response(taps)
        with self.assertRaises(ValueError):cascade_impulse_response([1],[1],'bad')


class PlotWidgetTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        self.root.withdraw();self.addCleanup(self.root.destroy)

    def test_impulse_modes_and_quadratic_tab(self):
        v=CalViewer(self.root,'test.bin',report())
        v.withdraw();self.root.update()
        self.assertIn('Quadratic correction',[v.tabs.tab(t,'text') for t in v.tabs.tabs()])
        v.vector.set('Acv10VFlatnessCoefs');v.plot_kind.set('Impulse response')
        self.assertEqual(len(v.curve),70)
        self.assertIn('index',v.x_label)
        v.mode.set('APP11 2.43 image1 cascade')
        self.assertEqual(len(v.curve),208)
        self.assertIn('us',v.x_label)
        self.assertAlmostEqual(sum(y for _,y in v.curve),1)
        self.assertEqual(len(v.canvas.find_withtag('impulse_sample')),208)
        v.max_x.set('nan');v._draw();self.assertFalse(v.visible)
        v.plot_kind.set('Magnitude');self.assertEqual(len(v.curve),4097)
        v.quadratic_plot.span.set('1')
        self.assertAlmostEqual(v.quadratic_plot.curve[-1][1],.05)
        v.quadratic_plot.span.set('bad')
        self.assertEqual(v.quadratic_plot.curve,[])

    def test_history_trends_reference_switch_and_empty_history(self):
        v=CalHistoryViewer(self.root,'test.bin',make_history())
        v.withdraw();self.root.update()
        self.assertIn('Slot trends',[v.tabs.tab(t,'text') for t in v.tabs.tabs()])
        v.reference.set('A0');self.root.update()
        # New tab shares the reference control with Changes.
        from utility3441x.cal_history_plot import CalHistoryPlot
        plot=next(child for tab in v.tabs.winfo_children() for child in tab.winfo_children()
                  if isinstance(child,CalHistoryPlot))
        self.assertIn('Reference A0',plot.status.cget('text'))
        self.assertEqual(len(plot.canvas.find_withtag('slot-A2')),1)
        self.assertEqual(len(plot.canvas.find_withtag('slot-A1')),0)
        empty=CalHistoryViewer(self.root,'empty.bin',{'slots':[]})
        empty.withdraw();self.root.update()


if __name__=='__main__':unittest.main()
