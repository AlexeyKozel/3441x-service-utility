import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from utility3441x.cal_files import read_operating_hours, save_cal_backup
from utility3441x.cal_journal_backup import backup_cal_journal
from test_cal_snapshots import payload
from utility3441x.cal_history import REGION_SIZE

class OperatingHoursTests(unittest.TestCase):
    def test_valid_and_zero(self):
        for value in ('266.822','0','1.2e3'):
            instrument=Mock();instrument.query_text.return_value='Elapsed Time Hours: '+value+'\n'
            result=read_operating_hours(instrument)
            self.assertEqual(result['status'],'available')
            self.assertEqual(result['operatingHours'],float(value))
            self.assertEqual(result['rawResponse'],instrument.query_text.return_value)
            instrument.query_text.assert_called_once_with('DIAG:PEEK:FIRMWARE? 24,0,0')

    def test_bad_reply_or_timeout_preserves_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            for i,reply in enumerate(('Elapsed Time Hours: -1','Elapsed Time Hours: NaN','oops',TimeoutError('timeout'))):
                instrument=Mock()
                if isinstance(reply,Exception):instrument.query_text.side_effect=reply
                else:instrument.query_text.return_value=reply
                runtime=read_operating_hours(instrument)
                self.assertIsNone(runtime['operatingHours']);self.assertEqual(runtime['status'],'unavailable')
                raw=payload();result=save_cal_backup(Path(folder),raw,{'serial':f'TEST{i}'},operating_time=runtime)
                self.assertEqual(Path(result['file']).read_bytes(),raw)
                meta=json.loads(Path(result['metadataFile']).read_text())
                self.assertEqual(meta['backup']['operatingTime'],runtime)

    def test_journal_records_hours(self):
        with tempfile.TemporaryDirectory() as folder:
            instrument=Mock();instrument.identity.return_value={'serial':'TEST'}
            instrument.read_memory.return_value=b'\xff'*REGION_SIZE
            instrument.query_text.return_value='Elapsed Time Hours: 266.822'
            result=backup_cal_journal(instrument,Path(folder))
            self.assertEqual(result['report']['operatingTime']['operatingHours'],266.822)
            self.assertEqual(instrument.mock_calls[-1][0],'query_text')
