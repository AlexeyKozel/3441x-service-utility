"""Offline checks for multi-file schema45 CAL snapshots and trends."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utility3441x.cal_snapshots import (default_reference, load_snapshots,
                                        ordered_snapshots, snapshot_trend)
from utility3441x.offline import load_schema45_registry


GAIN = "DcvGain0_1"
GAIN_OFFSET = next(row["offset"] for row in load_schema45_registry()["registry"]["rows"]
                   if row["name"] == GAIN)


def payload(gain: float = 1.0, *, invalid_checksum: bool = False) -> bytes:
    body = bytearray(4924)
    struct.pack_into(">d", body, GAIN_OFFSET, gain)
    check = (~sum(body)) & 0xFFFFFFFF
    if invalid_checksum:
        check ^= 1
    return struct.pack(">HII", 45, len(body), check) + body


def write_snapshot(folder: Path, name: str, gain: float = 1.0, *, serial=None,
                   saved_at=None, sidecar_hash=True, sidecar=True) -> Path:
    path = folder / name
    raw = payload(gain)
    path.write_bytes(raw)
    if sidecar:
        digest = hashlib.sha256(raw).hexdigest()
        report = {"sha256": digest if sidecar_hash else "0" * 64,
                  "backup": {"identity": {"serial": serial}, "savedAtUtc": saved_at}}
        path.with_suffix(path.suffix + ".json").write_text(
            json.dumps(report), encoding="utf-8")
    return path


class CalSnapshotTests(unittest.TestCase):
    def test_sidecar_date_precedence_conflict_and_bad_hash_fallback(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder_name:
            folder = Path(folder_name)
            path = write_snapshot(folder, "MY1_CAL_2026-01-01_00-00-00-000000Z.bin",
                                  serial="META1", saved_at="2026-01-02T03:00:00+03:00")
            snapshot = load_snapshots([path])[0]
            self.assertEqual(snapshot["serial"], "META1")
            self.assertEqual(snapshot["date"], datetime(2026, 1, 2, tzinfo=timezone.utc))
            self.assertEqual(snapshot["dateSource"], "sidecar")
            self.assertTrue(any("2026-01-02T00:00:00+00:00" in warning
                                and "2026-01-01T00:00:00+00:00" in warning
                                for warning in snapshot["warnings"]))
            self.assertTrue(any("META1" in warning and "MY1" in warning
                                for warning in snapshot["warnings"]))

            bad = write_snapshot(folder, "MY2_CAL_2026-02-01_00-00-00-000000Z.bin",
                                 serial="UNTRUSTED", saved_at="2020-01-01T00:00:00Z",
                                 sidecar_hash=False)
            fallback = load_snapshots([bad])[0]
            self.assertEqual(fallback["serial"], "MY2")
            self.assertEqual(fallback["date"], datetime(2026, 2, 1, tzinfo=timezone.utc))
            self.assertEqual(fallback["dateSource"], "filename")
            self.assertTrue(any("SHA-256" in warning for warning in fallback["warnings"]))

            malformed = write_snapshot(folder, "MY3_CAL_2026-03-01_00-00-00-000000Z.bin",
                                       sidecar=False)
            malformed.with_suffix(malformed.suffix + ".json").write_text("{broken", encoding="utf-8")
            ignored = load_snapshots([malformed])[0]
            self.assertEqual(ignored["serial"], "MY3")
            self.assertEqual(ignored["dateSource"], "filename")
            self.assertTrue(any("could not be read" in warning for warning in ignored["warnings"]))

    def test_unknown_date_is_last_and_default_uses_first_when_all_undated(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder_name:
            folder = Path(folder_name)
            dated = write_snapshot(folder, "MY1_CAL_2026-01-01_00-00-00-000000Z.bin", sidecar=False)
            undated = write_snapshot(folder, "legacy.bin", sidecar=False)
            snapshots = load_snapshots([undated, dated])
            self.assertEqual([item["path"] for item in ordered_snapshots(snapshots)],
                             [str(dated), str(undated)])
            self.assertEqual(default_reference(snapshots)["path"], str(dated))
            unknown = load_snapshots([undated])[0]
            self.assertIsNone(unknown["date"])
            self.assertEqual(unknown["dateSource"], "unknown")
            self.assertEqual(default_reference([unknown])["id"], unknown["id"])
            unknown_dated_path = write_snapshot(
                folder, "legacy_dated.bin", sidecar=True, serial=None,
                saved_at="2026-01-03T00:00:00Z")
            unknown_dated = load_snapshots([unknown_dated_path])[0]
            trend = snapshot_trend([unknown_dated], GAIN, unknown_dated["id"])
            self.assertFalse(trend["available"])
            self.assertIn("serial", trend["reason"])

    def test_more_than_32_snapshots_are_sorted_without_truncation(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder_name:
            folder = Path(folder_name)
            paths = [write_snapshot(folder, f"s{i:02}_CAL_2026-01-{(i % 28) + 1:02}_00-00-00-000000Z.bin",
                                    sidecar=False) for i in range(40)]
            snapshots = load_snapshots(paths)
            ordered = ordered_snapshots(snapshots)
            self.assertEqual(len(ordered), 40)
            self.assertEqual([item["date"] for item in ordered],
                             sorted(item["date"] for item in snapshots))

    def test_trend_filters_serial_and_excludes_undated_snapshots(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder_name:
            folder = Path(folder_name)
            first = write_snapshot(folder, "a_CAL_2026-01-01_00-00-00-000000Z.bin", 2.0,
                                   serial="SAME", saved_at="2026-01-01T00:00:00Z")
            same = write_snapshot(folder, "b_CAL_2026-01-02_00-00-00-000000Z.bin", 3.0,
                                  serial="SAME", saved_at="2026-01-02T00:00:00Z")
            other = write_snapshot(folder, "c_CAL_2026-01-03_00-00-00-000000Z.bin", 9.0,
                                   serial="OTHER", saved_at="2026-01-03T00:00:00Z")
            undated = write_snapshot(folder, "unknown.bin", 4.0, sidecar=False)
            snapshots = load_snapshots([same, other, undated, first])
            ref = next(item for item in snapshots if item["path"] == str(first))
            trend = snapshot_trend(snapshots, GAIN, ref["id"])
            self.assertTrue(trend["available"])
            self.assertEqual([point["id"] for point in trend["points"]],
                             [item["id"] for item in ordered_snapshots(snapshots)
                              if item["serial"] == "SAME" and item["date"] is not None])
            self.assertEqual(trend["points"][0]["y"], 0.0)
            self.assertAlmostEqual(trend["points"][1]["y"], 500_000)
            self.assertTrue(all(set(point) == {"x", "y", "id"} for point in trend["points"]))

    def test_zero_relative_reference_is_unavailable(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder_name:
            folder = Path(folder_name)
            path = write_snapshot(folder, "MY1_CAL_2026-01-01_00-00-00-000000Z.bin", 0.0,
                                  serial="SAME", saved_at="2026-01-01T00:00:00Z")
            snapshot = load_snapshots([path])[0]
            trend = snapshot_trend([snapshot], GAIN, snapshot["id"])
            self.assertFalse(trend["available"])
            self.assertIn("zero", trend["reason"])
            self.assertEqual(trend["points"], [])

    def test_invalid_file_error_names_file_and_requires_exact_valid_schema45(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            load_snapshots([])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder_name:
            folder = Path(folder_name)
            bad = folder / "bad.bin"
            bad.write_bytes(payload(invalid_checksum=True))
            with self.assertRaisesRegex(ValueError, "bad.bin.*checksum"):
                load_snapshots([bad])
            short = folder / "short.bin"
            short.write_bytes(b"not CAL")
            with self.assertRaisesRegex(ValueError, "short.bin.*invalid CAL"):
                load_snapshots([short])


if __name__ == "__main__":
    unittest.main()
