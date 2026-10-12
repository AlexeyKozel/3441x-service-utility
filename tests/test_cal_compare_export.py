import csv
from datetime import datetime,timezone
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from utility3441x.cal_compare_export import export_comparison_csv

class ComparisonExportTests(unittest.TestCase):
    def test_context_precision_and_escaping(self):
        snapshot={'path':'=bad,name.bin','serial':None,'date':datetime(2026,10,9,tzinfo=timezone.utc),'dateSource':'manual','report':{'sha256':'abc'}}
        row=dict(name='AdcQuad',title='Quadratic, coefficient',changed=True,reference='1',selected='2',referenceRaw='1.1234567890123456',selectedRaw='2',delta='0.8765432109876544',referenceHex='abcd',selectedHex='ffff')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'comparison.csv'
            self.assertEqual(export_comparison_csv(path,snapshot,snapshot,[row],['+1 ppm'],filters='Only changed=True'),1)
            self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
            with path.open(encoding='utf-8-sig',newline='') as stream: records=list(csv.DictReader(stream))
            self.assertEqual(len(records),1)
            r=records[0]
            self.assertEqual(r['label'],'Quadratic, coefficient')
            self.assertEqual(r['reference_stored'],'1.1234567890123456')
            self.assertEqual(r['reference_file'],"'=bad,name.bin")
            self.assertEqual(r['reference_serial'],'')
            self.assertEqual(r['reference_saved_utc'],'2026-10-09T00:00:00+00:00')
            self.assertEqual(r['reference_hex'],'abcd')

    def test_empty_view_still_exports_header(self):
        s={'path':'a.bin','report':{}}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'empty.csv';export_comparison_csv(path,s,s,[],[],filters='Only changed=True')
            with path.open(encoding='utf-8-sig') as stream:self.assertEqual(len(list(csv.reader(stream))),1)
