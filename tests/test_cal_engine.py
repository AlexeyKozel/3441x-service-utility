import sys,unittest,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from utility3441x.cal_engine import CalSnapshot,comparison_rows,scalar_change
from utility3441x.offline import parse_cal_payload
from test_cal_snapshots import payload

class CalEngineTests(unittest.TestCase):
    def test_engine_import_does_not_load_tk(self):
        code="import sys; from utility3441x import cal_engine, cal_snapshots; assert 'tkinter' not in sys.modules"
        run=subprocess.run([sys.executable,'-B','-c',code],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)

    def test_scalar_boundaries(self):
        self.assertEqual(scalar_change(2,3,'ppm'),500000)
        self.assertEqual(scalar_change(0,3,'ohm_delta'),3)
        self.assertIsNone(scalar_change(0,3,'ppm'))
        self.assertIsNone(scalar_change(float('nan'),3,'ppm'))
        self.assertIsNone(scalar_change(1e-300,1e300,'ppm'))
        self.assertIsNone(scalar_change(2,3,'unsupported'))

    def test_same_snapshot_view_and_comparison(self):
        a,b=payload(2),payload(3)
        x=CalSnapshot(parse_cal_payload(a,explain=True),a[10:].hex())
        y=CalSnapshot(parse_cal_payload(b,explain=True),b[10:].hex())
        rows=comparison_rows(x.as_record(),y.as_record())
        changed=[r for r in rows if r['changed']]
        self.assertEqual(len(changed),1)
        self.assertEqual(changed[0]['interpretedDelta'],'+500000 ppm')
        self.assertEqual([r['reference'] for r in rows],[d['value'] for d in x.display])
        self.assertEqual([r['selected'] for r in rows],[d['value'] for d in y.display])
