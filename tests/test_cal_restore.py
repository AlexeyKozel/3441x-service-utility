from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.cal_history import REGION_OFFSET, SLOT_SIZE, SLOT_COUNT  # noqa: E402
from utility3441x.cal_restore import cal_write_frame, restore_calibration  # noqa: E402
from utility3441x.instrument import VisaInstrument  # noqa: E402
from utility3441x.offline import NOR_BASE, parse_cal_payload  # noqa: E402


IDENTITY = {"model": "34411A", "serial": "TEST000001", "firmware": "2.43"}
def make_payload(first_byte: int = 0) -> bytes:
    body = bytes([first_byte]) + bytes(4923)
    checksum = (~sum(body)) & 0xFFFFFFFF
    return struct.pack(">HII", 45, 4924, checksum) + body


class FakeInstrument:
    def __init__(self, working: bytes, *, identity=None):
        self.working = working
        self.identity_value = dict(IDENTITY if identity is None else identity)
        self.identity_calls = 0
        self.read_calls = 0
        self.write_calibration_calls = []
        self.write_text_calls = []
        self.memory_calls = []
        self.error_queue = "0,No error"
        self.security = "0"
        self.opc = "1"
        self.opc_error = None
        self.import_error = None
        self.store_error = None
        self.readback_override = None
        self.nor_override = None
        self.saved = None

    def identity(self):
        self.identity_calls += 1
        return dict(self.identity_value)

    def query_text(self, command):
        if command == "SYST:ERR?":
            return self.error_queue
        if command == "CAL:SEC:STAT?":
            return self.security
        if command == "*OPC?":
            if self.opc_error is not None:
                raise self.opc_error
            return self.opc
        raise AssertionError(f"Unexpected query: {command}")

    def read_calibration(self):
        self.read_calls += 1
        if self.readback_override is not None and self.read_calls >= 3:
            payload = self.readback_override
        else:
            payload = self.working
        return payload, parse_cal_payload(payload)

    def write_calibration(self, payload):
        self.write_calibration_calls.append(payload)
        if self.import_error is not None:
            raise self.import_error
        self.working = payload

    def write_text(self, command):
        self.write_text_calls.append(command)
        if self.store_error is not None:
            raise self.store_error
        if command == "CAL:STORE":
            self.saved = self.working if self.nor_override is None else self.nor_override

    def read_memory(self, address, size):
        self.memory_calls.append((address, size))
        first_slot = NOR_BASE + REGION_OFFSET
        for index in range(SLOT_COUNT):
            slot_address = first_slot + SLOT_SIZE * index
            if address == slot_address and size == 16:
                if self.saved is None or index != 0:
                    return b"\xff" * size
                version, length, checksum = struct.unpack(">HII", self.saved[:10])
                return struct.pack(">HHIII", 0xA5, version, length + 8,
                                   length, checksum)
            if address == slot_address + 16:
                if self.saved is None or index != 0:
                    return b"\xff" * size
                return self.saved[10:10 + size]
        return b"\xff" * size


class CalRestoreTests(unittest.TestCase):
    before = make_payload()
    target = make_payload(1)

    def setUp(self):
        self.validation_temp = ROOT.parents[2] / "validation" / "rc15_cal_restore_20261009" / "temp"
        self.validation_temp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.validation_temp)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.source = self.root / "TEST000001_CAL_2026-10-09_00-00-00-000000Z.bin"
        self.source.write_bytes(self.target)

    def run_restore(self, instrument, *, payload=None, backup_folder=None, answers=None):
        answers = iter(answers if answers is not None else [True, True])
        confirmations = []

        def confirm(title, message):
            confirmations.append((title, message))
            return next(answers)

        result = restore_calibration(
            instrument,
            self.target if payload is None else payload,
            self.source,
            self.backups if backup_folder is None else backup_folder,
            confirm,
        )
        return result, confirmations

    def test_success_verifies_working_readback_and_current_nor_record(self):
        instrument = FakeInstrument(self.before)
        result, confirmations = self.run_restore(instrument)
        self.assertEqual(result["status"], "saved_and_verified")
        self.assertEqual(result["savedRecord"]["slot"], "A0")
        self.assertEqual(instrument.working, self.target)
        self.assertEqual(instrument.write_calibration_calls, [self.target])
        self.assertEqual(instrument.write_text_calls, ["CAL:STORE"])
        self.assertEqual([item[0] for item in confirmations],
                         ["Restore working CAL", "Save CAL to NOR"])
        self.assertEqual(Path(result["backupFile"]).read_bytes(), self.before)

    def test_serial_mismatch_decline_stops_before_cal_reads_or_writes(self):
        instrument = FakeInstrument(self.before)
        instrument.identity_value['serial'] = 'TEST99999999'
        result, confirmations = self.run_restore(instrument, answers=[False])
        self.assertEqual(result, {"status": "cancelled", "written": False})
        self.assertEqual(confirmations[0][0], "CAL serial number")
        self.assertEqual(instrument.read_calls, 0)
        self.assertEqual(instrument.write_calibration_calls, [])
        self.assertEqual(instrument.write_text_calls, [])

    def test_invalid_payload_is_rejected_before_identity(self):
        instrument = FakeInstrument(self.before)
        with self.assertRaises(ValueError):
            self.run_restore(instrument, payload=self.target[:-1])
        self.assertEqual(instrument.identity_calls, 0)

    def test_unsupported_model_or_firmware_stops_before_cal_reads(self):
        for identity in (
            {**IDENTITY, "model": "34410A"},
            {**IDENTITY, "firmware": "2.42"},
        ):
            with self.subTest(identity=identity):
                instrument = FakeInstrument(self.before, identity=identity)
                with self.assertRaisesRegex(ValueError, "currently supports only"):
                    self.run_restore(instrument)
                self.assertEqual(instrument.read_calls, 0)
                self.assertEqual(instrument.write_calibration_calls, [])
                self.assertEqual(instrument.write_text_calls, [])

    def test_backup_failure_prevents_all_writes(self):
        instrument = FakeInstrument(self.before)
        blocked_backup_path = self.root / "backup-is-a-file"
        blocked_backup_path.write_text("occupied")
        with self.assertRaises(OSError):
            self.run_restore(instrument, backup_folder=blocked_backup_path)
        self.assertEqual(instrument.write_calibration_calls, [])
        self.assertEqual(instrument.write_text_calls, [])

    def test_import_failure_timeout_and_readback_mismatch_never_store_or_retry(self):
        cases = ("import_failure", "operation_timeout", "readback_mismatch")
        for case in cases:
            with self.subTest(case=case):
                instrument = FakeInstrument(self.before)
                if case == "import_failure":
                    instrument.import_error = IOError("short raw write")
                elif case == "operation_timeout":
                    instrument.opc_error = TimeoutError("operation timeout")
                else:
                    instrument.readback_override = self.before
                with self.assertRaises(RuntimeError):
                    self.run_restore(instrument)
                self.assertEqual(len(instrument.write_calibration_calls), 1)
                self.assertEqual(instrument.write_text_calls, [])

    def test_store_timeout_is_not_retried(self):
        instrument = FakeInstrument(self.before)
        instrument.store_error = TimeoutError("store timeout")
        with self.assertRaises(RuntimeError):
            self.run_restore(instrument)
        self.assertEqual(len(instrument.write_calibration_calls), 1)
        self.assertEqual(instrument.write_text_calls, ["CAL:STORE"])

    def test_cancel_second_confirmation_leaves_verified_working_only(self):
        instrument = FakeInstrument(self.before)
        result, confirmations = self.run_restore(instrument, answers=[True, False])
        self.assertEqual(result["status"], "working_only")
        self.assertEqual([item[0] for item in confirmations],
                         ["Restore working CAL", "Save CAL to NOR"])
        self.assertEqual(instrument.working, self.target)
        self.assertEqual(instrument.write_text_calls, [])

    def test_nor_mismatch_does_not_report_success(self):
        instrument = FakeInstrument(self.before)
        instrument.nor_override = self.before
        with self.assertRaisesRegex(RuntimeError, "NOR CAL does not match"):
            self.run_restore(instrument)
        self.assertEqual(len(instrument.write_calibration_calls), 1)
        self.assertEqual(instrument.write_text_calls, ["CAL:STORE"])

    def test_secured_cal_stops_before_backup_and_writes(self):
        instrument = FakeInstrument(self.before)
        instrument.security = "1"
        with self.assertRaisesRegex(RuntimeError, "secured"):
            self.run_restore(instrument)
        self.assertEqual(list(self.backups.iterdir()), [])
        self.assertEqual(instrument.write_calibration_calls, [])
        self.assertEqual(instrument.write_text_calls, [])

    def test_already_loaded_saves_backup_but_does_not_store_or_prompt(self):
        instrument = FakeInstrument(self.target)
        instrument.saved = self.target
        result, confirmations = self.run_restore(instrument, answers=[])
        self.assertEqual(result["status"], "already_saved")
        self.assertEqual(confirmations, [])
        self.assertEqual(instrument.write_calibration_calls, [])
        self.assertEqual(instrument.write_text_calls, [])

    def test_matching_working_cal_can_be_committed_without_reimport(self):
        instrument = FakeInstrument(self.target)
        instrument.saved = self.before
        result, confirmations = self.run_restore(instrument, answers=[True])
        self.assertEqual(result['status'], 'saved_and_verified')
        self.assertEqual(instrument.write_calibration_calls, [])
        self.assertEqual(instrument.write_text_calls, ['CAL:STORE'])
        self.assertEqual([title for title, _ in confirmations], ['Save CAL to NOR'])

    def test_write_frame_is_exact_binary_ieee_block(self):
        frame = cal_write_frame(self.target)
        self.assertEqual(frame, b"CAL:DATA:ALL #44934" + self.target + b"\n")
        self.assertEqual(frame[13:15], b"#4")
        self.assertEqual(frame[15:19], b"4934")

    def test_visa_calibration_short_raw_write_raises_without_retry(self):
        class RawWriter:
            def __init__(self):
                self.frames = []

            def write_raw(self, frame):
                self.frames.append(frame)
                return len(frame) - 1

        instrument = VisaInstrument.__new__(VisaInstrument)
        instrument._inst = RawWriter()
        with self.assertRaisesRegex(RuntimeError, "short write"):
            instrument.write_calibration(self.target)
        self.assertEqual(instrument._inst.frames,
                         [b"CAL:DATA:ALL #44934" + self.target + b"\n"])

    def test_binary_query_preserves_embedded_lf_and_consumes_response_lf(self):
        class Resource:
            def __init__(self, response):
                self.response = response
                self.offset = 0
                self.read_termination = "\n"
                self.commands = []

            def write(self, command):
                self.commands.append(command)

            def read_bytes(self, size):
                result = self.response[self.offset:self.offset + size]
                self.offset += len(result)
                return result

        payload = b"row\nnext\x00binary"
        response = b"#2" + f"{len(payload):02d}".encode("ascii") + payload + b"\n"
        resource = Resource(response)
        instrument = VisaInstrument.__new__(VisaInstrument)
        instrument._inst = resource

        result = instrument.query_binary_block("CAL:DATA:ALL?")

        self.assertEqual(result, payload)
        self.assertEqual(resource.offset, len(response))
        self.assertEqual(resource.commands, ["CAL:DATA:ALL?"])
        self.assertEqual(resource.read_termination, "\n")

    def test_binary_query_rejects_bad_terminator_and_restores_read_termination(self):
        class Resource:
            def __init__(self, response):
                self.response = response
                self.offset = 0
                self.read_termination = "\r\n"

            def write(self, _command):
                pass

            def read_bytes(self, size):
                result = self.response[self.offset:self.offset + size]
                self.offset += len(result)
                return result

        resource = Resource(b"#14data!")
        instrument = VisaInstrument.__new__(VisaInstrument)
        instrument._inst = resource

        with self.assertRaisesRegex(RuntimeError, "terminator"):
            instrument.query_binary_block("CAL:DATA:ALL?")

        self.assertEqual(resource.read_termination, "\r\n")


if __name__ == "__main__":
    unittest.main()
