import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utility3441x.cal_journal_backup import backup_cal_journal
from utility3441x.cal_history import scan_cal_history, REGION_OFFSET, REGION_SIZE
from utility3441x.offline import NOR_BASE
from test_cal_history import slot


class JournalBackupTests(unittest.TestCase):
    def setUp(self):
        self.raw = (slot(0) + slot(0xA5) + slot(0, corrupt=True)).ljust(REGION_SIZE, b'\xff')
        self.instrument = Mock()
        self.instrument.identity.return_value = {'model': '34411A', 'serial': 'TEST12345678', 'firmware': '2.43'}
        self.instrument.read_memory.return_value = self.raw
        self.stamp = datetime(2026, 10, 9, tzinfo=timezone.utc)

    def test_save_and_open_preserves_every_slot_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            result = backup_cal_journal(self.instrument, Path(folder), saved_at=self.stamp)
            path = Path(result['file'])
            self.assertEqual(path.name, 'TEST12345678_CAL_HISTORY_2026-10-09_00-00-00-000000Z.bin')
            self.assertEqual(path.read_bytes(), self.raw)
            self.instrument.read_memory.assert_called_once_with(NOR_BASE + REGION_OFFSET, REGION_SIZE, progress=None)
            report = scan_cal_history(path.read_bytes())
            self.assertEqual(report['inputKind'], 'cal-journal')
            self.assertEqual(report['currentSlot'], 'A1')
            self.assertEqual(report['slots'][2]['status'], 'Invalid')
            self.assertEqual(report['slots'][31]['status'], 'Empty')
            meta = json.loads(Path(result['metadataFile']).read_text())
            self.assertEqual(meta['sha256'], report['sha256Region'])
            with self.assertRaises(FileExistsError):
                backup_cal_journal(self.instrument, Path(folder), saved_at=self.stamp)
            self.assertEqual(self.instrument.read_memory.call_count, 1)
            self.assertEqual({call[0] for call in self.instrument.mock_calls}, {'identity', 'read_memory', 'query_text'})
            self.assertEqual(meta['operatingTime']['status'], 'unavailable')

    def test_short_read_or_identity_change_does_not_save(self):
        for short in (True, False):
            with self.subTest(short=short), tempfile.TemporaryDirectory() as folder:
                if short:
                    self.instrument.read_memory.return_value = self.raw[:-1]
                else:
                    self.instrument.read_memory.return_value = self.raw
                    self.instrument.identity.side_effect = [
                        {'serial': 'TEST12345678'}, {'serial': 'TEST87654321'}]
                with self.assertRaises(RuntimeError):
                    backup_cal_journal(self.instrument, Path(folder))
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_truncated_and_single_payload_are_rejected(self):
        for raw in (self.raw[:-1], self.raw+b'\xff', bytes(4934)):
            with self.assertRaises(ValueError):
                scan_cal_history(raw)
