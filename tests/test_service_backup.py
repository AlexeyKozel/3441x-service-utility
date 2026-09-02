from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x import backup as backup_module  # noqa: E402
from utility3441x import instrument as instrument_module  # noqa: E402
from utility3441x.backup import create_service_backup  # noqa: E402
from utility3441x.instrument import dump_nor  # noqa: E402
from utility3441x.offline import NOR_SIZE, parse_cal_payload  # noqa: E402


def cal_payload(body: bytes = b"\x01\x02\x03\x04") -> bytes:
    """Build a CAL:DATA:ALL payload that satisfies parse_cal_payload."""

    checksum = (~sum(body)) & 0xFFFFFFFF
    return (
        (45).to_bytes(2, "big")
        + len(body).to_bytes(4, "big")
        + checksum.to_bytes(4, "big")
        + body
    )


class ServiceBackupTests(unittest.TestCase):
    """create_service_backup must run to completion on Windows.

    It used to fsync a handle opened "rb"; on Windows os.fsync is _commit(),
    which needs write access and raises OSError [Errno 9]. The failure landed
    after the whole backup -- including an 8 MiB NOR read -- had been done.
    """

    class FakeInstrument:
        resource = "TCPIP0::198.51.100.7::inst0::INSTR"
        session_id = "00000000-0000-0000-0000-000000000000"

        @staticmethod
        def identity() -> dict[str, str]:
            return {
                "manufacturer": "Agilent Technologies",
                "model": "34410A",
                "serial": "MY00000001",
                "firmware": "2.43-2.40-0.09-46-09",
                "raw": "Agilent Technologies,34410A,MY00000001,2.43-2.40-0.09-46-09",
            }

        @staticmethod
        def diagnostics() -> dict[str, object]:
            return {"identity": ServiceBackupTests.FakeInstrument.identity()}

        @staticmethod
        def read_calibration() -> tuple[bytes, dict[str, object]]:
            payload = cal_payload()
            return payload, parse_cal_payload(payload)

    def test_backup_completes_and_verifies(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name) / "backup"
            result = create_service_backup(
                self.FakeInstrument(), folder, include_nor=False
            )

        self.assertTrue(result["allHashesValid"])
        self.assertEqual(
            sorted(item["name"] for item in result["files"]),
            [
                "calibration_current.bin",
                "calibration_current.json",
                "diagnostics.json",
                "identity.json",
            ],
        )

    def test_written_files_are_durable(self):
        synced: list[int] = []
        real_fsync = os.fsync

        def counting_fsync(fd: int) -> None:
            synced.append(fd)
            real_fsync(fd)

        with tempfile.TemporaryDirectory() as name:
            folder = Path(name) / "backup"
            backup_module.os.fsync = counting_fsync
            try:
                create_service_backup(
                    self.FakeInstrument(), folder, include_nor=False
                )
            finally:
                backup_module.os.fsync = real_fsync

        # identity, diagnostics, calibration bin, calibration json, manifest
        self.assertEqual(len(synced), 5)


class DumpNorSyncTests(unittest.TestCase):
    """The resume file must be synced whatever batch size is used.

    The old boundary test `done % 0x10000 == 0` only ever fired when
    batch_words * 2 divided 64 KiB. With batch_words=48 it never fired, so the
    resume file was never synced at all.
    """

    class FakeInstrument:
        @staticmethod
        def read_memory(address: int, size: int, *, batch_words: int = 16) -> bytes:
            return bytes(size)

    def _sync_count(self, batch_words: int) -> int:
        synced: list[int] = []
        real_fsync = os.fsync

        def counting_fsync(fd: int) -> None:
            synced.append(fd)
            real_fsync(fd)

        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / "main_flash_cpu.bin"
            instrument_module.os.fsync = counting_fsync
            try:
                dump_nor(
                    self.FakeInstrument(),
                    output,
                    resume=False,
                    batch_words=batch_words,
                )
            finally:
                instrument_module.os.fsync = real_fsync
            self.assertEqual(output.stat().st_size, NOR_SIZE)
        return len(synced)

    def test_batch_that_divides_64k_is_synced(self):
        self.assertEqual(self._sync_count(16), NOR_SIZE // 0x10000)

    def test_batch_that_does_not_divide_64k_is_still_synced(self):
        self.assertGreaterEqual(self._sync_count(48), NOR_SIZE // 0x10000)


if __name__ == "__main__":
    unittest.main()
