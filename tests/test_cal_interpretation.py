from __future__ import annotations

import contextlib
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utility3441x import cal_interpretation
from utility3441x.cli import main
from utility3441x.offline import parse_cal_payload
from utility3441x.instrument import VisaInstrument


def payload(version=45, size=4924, corrupt=False):
    body = bytearray(size)
    if size == 4924:
        struct.pack_into('>d', body, 0, -0.125)
        struct.pack_into('>d', body, 8, 12.0)
    checksum = (~sum(body)) & 0xffffffff
    return struct.pack('>HII', version, size, checksum ^ int(corrupt)) + body


class CalInterpretationTests(unittest.TestCase):
    def test_instrument_backup_file_opens_in_inspect_cal(self):
        expected = payload()
        instrument = object.__new__(VisaInstrument)
        transport = MagicMock()
        transport.read_bytes.side_effect = [b'#4', b'4934', expected]
        instrument._inst = transport
        context = MagicMock()
        context.__enter__.return_value = instrument
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'saved_cal.bin'
            with patch('utility3441x.cli.VisaInstrument', return_value=context):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['backup-cal', '--resource', 'offline-test',
                                           '--output', str(path)]), 0)
            self.assertEqual(path.read_bytes(), expected)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(['inspect-cal', str(path), '--explain']), 0)
            report = json.loads(output.getvalue())
            self.assertTrue(report['checksumValid'])
            self.assertEqual(report['schema45']['elementCount'], 1072)
        transport.write.assert_called_once_with('CAL:DATA:ALL?')

    def test_raw_body_error_through_gui_cli_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cal_body.bin'
            path.write_bytes(payload()[10:])
            result = subprocess.run(
                [sys.executable, '-B', str(ROOT / '3441x_service_utility.py'),
                 'inspect-cal', str(path), '--explain'],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertIn('4934 bytes', result.stderr)
        self.assertIn('*_cal_payload_reconstructed.bin', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_explanations_preserve_every_raw_value_and_provenance(self):
        plain = parse_cal_payload(payload())
        explained = parse_cal_payload(payload(), explain=True)
        self.assertNotIn('interpretation', plain)
        self.assertEqual(len(explained['schema45']['meanings']), 38)
        for old, new in zip(plain['schema45']['values'], explained['schema45']['values']):
            self.assertEqual(old, {k: v for k, v in new.items() if k != 'meaning'})
            self.assertIn(new['meaning']['family'], explained['schema45']['meanings'])
        rows = {v['name']: v for v in explained['schema45']['values']}
        self.assertEqual(rows['Adc_DcOffset[DCV]']['meaning']['groupId'], 0)
        self.assertEqual(rows['Adc_DcOffset[ACV]']['meaning']['groupId'], 1)
        self.assertEqual(rows['Adc_DcOffset[ACI]']['meaning']['groupId'], 2)
        self.assertEqual(rows['AdcQuad']['value'], -0.125)
        self.assertEqual(explained['interpretation']['valueAssessment'], 'not_performed')

    def test_unresolved_consumers_stay_open(self):
        families = parse_cal_payload(payload(), explain=True)['schema45']['meanings']
        for name in ('AcvSlowDcGainSquared', 'McDelay', 'MzDelay'):
            self.assertEqual(families[name]['usage_status'], 'open')

    def test_same_length_does_not_authorize_unknown_version_meanings(self):
        for version, size in ((44, 4924), (46, 4924), (45, 16)):
            with self.subTest(version=version, size=size):
                report = parse_cal_payload(payload(version, size), explain=True)
                self.assertEqual(report['interpretation']['status'], 'unavailable')
                self.assertNotIn('meanings', report.get('schema45', {}))

    def test_bad_checksum_is_not_promoted_to_valid_calibration(self):
        report = parse_cal_payload(payload(corrupt=True), explain=True)
        self.assertFalse(report['checksumValid'])
        self.assertEqual(report['interpretation']['payloadIntegrity'], 'checksum_mismatch')
        self.assertEqual(report['interpretation']['valueAssessment'], 'not_performed')

    def test_misaligned_binding_is_rejected_before_annotation(self):
        report = parse_cal_payload(payload())
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for name in ('schema45_registry_snapshot.json', 'cal_meanings_v1.json', 'cal_bindings_v1.json'):
                (target / name).write_bytes((cal_interpretation.DATA / name).read_bytes())
            bindings = json.loads((target / 'cal_bindings_v1.json').read_text())
            bindings['rows'][1]['offset'] += 8
            (target / 'cal_bindings_v1.json').write_text(json.dumps(bindings), encoding='utf-8')
            with patch.object(cal_interpretation, 'DATA', target):
                with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                    cal_interpretation.add_cal_interpretation(report)
        self.assertTrue(all('meaning' not in row for row in report['schema45']['values']))

    def test_cli_explain_emits_self_contained_family_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'cal.bin'
            p.write_bytes(payload())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(['inspect-cal', str(p), '--explain']), 0)
            report = json.loads(output.getvalue())
        self.assertEqual(report['schema45']['elementCount'], 1072)
        self.assertEqual(report['interpretation']['status'], 'available')
        self.assertTrue(report['schema45']['meanings']['HeaterGain']['summary'])


if __name__ == '__main__':
    unittest.main()
