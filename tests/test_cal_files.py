"""Serial/date backup naming and future restore target checks, offline only."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from utility3441x.cal_files import backup_filename, filename_serial, check_restore_target, save_cal_backup
from utility3441x.offline import parse_cal_payload


class CalFileTests(unittest.TestCase):
    stamp=datetime(2026,10,9,15,34,56,123456,tzinfo=timezone(timedelta(hours=3)))
    identity={'serial':'TEST000001','model':'34411A','firmware':'2.43'}
    payload=struct.pack('>HII',45,4924,0xffffffff)+bytes(4924)

    def test_utc_name_and_serial_roundtrip(self):
        name=backup_filename(self.identity['serial'],self.stamp)
        self.assertEqual(name,'TEST000001_CAL_2026-10-09_12-34-56-123456Z.bin')
        self.assertEqual(filename_serial(name),'TEST000001')
        self.assertIsNone(filename_serial(name.replace('2026-10-09','2026-99-99')))
        self.assertIsNone(filename_serial('calibration_current.bin'))
        for serial in ('','../bad','a/b','a\\b',None):
            with self.assertRaises(ValueError):backup_filename(serial,self.stamp)
        with self.assertRaises(ValueError):backup_filename('MY1',datetime(2026,1,1))

    def test_explicit_mismatch_and_unknown_confirmation(self):
        path=backup_filename('MY1',self.stamp)
        self.assertFalse(check_restore_target(path,'MY1')['requiresConfirmation'])
        mismatch=check_restore_target(path,'MY2')
        self.assertTrue(mismatch['requiresConfirmation'])
        self.assertIn('MY1',mismatch['message']);self.assertIn('MY2',mismatch['message'])
        self.assertIn('Are you sure you want to continue?',mismatch['message'])
        self.assertTrue(check_restore_target('legacy.bin','MY2')['requiresConfirmation'])
        with self.assertRaises(ValueError):check_restore_target(path,'')

    def test_binary_unchanged_identity_sidecar_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            result=save_cal_backup(Path(folder),self.payload,self.identity,saved_at=self.stamp)
            p=Path(result['file']);self.assertEqual(p.read_bytes(),self.payload)
            self.assertTrue(parse_cal_payload(p.read_bytes())['checksumValid'])
            meta=json.loads(Path(result['metadataFile']).read_text())
            self.assertEqual(meta['backup']['identity'],self.identity)
            self.assertEqual(meta['backup']['savedAtUtc'],'2026-10-09T12:34:56.123456+00:00')
            with self.assertRaises(FileExistsError):save_cal_backup(Path(folder),self.payload,self.identity,saved_at=self.stamp)
            legacy=save_cal_backup(Path(folder),self.payload,self.identity,saved_at=self.stamp,explicit_path=Path(folder)/'legacy.bin')
            self.assertIsNone(legacy['report']['backup']['filenameSerial'])

    def test_invalid_checksum_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):save_cal_backup(Path(folder),self.payload[:-1]+b'\x01',self.identity,saved_at=self.stamp)
            self.assertEqual(list(Path(folder).iterdir()),[])


if __name__=='__main__':unittest.main()
