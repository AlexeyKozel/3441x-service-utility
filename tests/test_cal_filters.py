from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utility3441x.cal_filters import (  # noqa: E402
    CONDITIONAL_ACI_EVENT_PERIOD_G3,
    CONDITIONAL_ACV_EVENT_PERIOD_G3,
    CONDITIONAL_G3_HZ,
    cascade_response,
    filter_vectors,
    response,
)


def explained_report() -> dict:
    values = []
    for name, family, raw in (("AcvRangeFlatnessCoefs", "flatness", 0xFFFF),
                              ("AcvLpFilter", "lp", 0x8000)):
        for index in range(70):
            values.append({
                "type": "int32", "value": raw if index == 0 else 1,
                "meaning": {"family": family, "nameBase": name,
                            "elementIndex": index},
            })
    while len(values) < 1072:
        values.append({"type": "int32", "value": 0,
                       "meaning": {"family": "other", "nameBase": "Other",
                                   "elementIndex": len(values)}})
    return {"version": 45, "bodyLength": 4924,
            "interpretation": {"status": "available"},
            "schema45": {"elementCount": 1072, "values": values}}


class CalFilterMathTests(unittest.TestCase):
    def test_vector_extraction_uses_exact_meanings_and_signed_low16(self):
        vectors = filter_vectors(explained_report())
        self.assertEqual(len(vectors), 2)
        self.assertEqual(vectors["AcvRangeFlatnessCoefs"][0], -1)
        self.assertEqual(vectors["AcvLpFilter"][0], -32768)
        self.assertEqual(len(vectors["AcvRangeFlatnessCoefs"]), 70)

    def test_vector_rejects_unknown_schema_and_incomplete_vector(self):
        report = explained_report()
        report["version"] = 44
        with self.assertRaises(ValueError):
            filter_vectors(report)
        report = explained_report()
        report["schema45"]["values"] = report["schema45"]["values"][:-1]
        with self.assertRaises(ValueError):
            filter_vectors(report)

    def test_single_tap_is_zero_db_at_dc_and_nyquist(self):
        curve = response([7], points=3)
        self.assertEqual(curve, [(0.0, 0.0), (0.25, 0.0), (0.5, 0.0)])

    def test_two_tap_analytic_dc_and_nyquist(self):
        curve = response([1, 1], points=3)
        self.assertEqual(curve[0], (0.0, 0.0))
        self.assertAlmostEqual(curve[1][1], 20 * math.log10(math.sqrt(0.5)), places=12)
        self.assertLess(curve[2][1], -300.0)

    def test_response_rejects_invalid_math_inputs(self):
        for taps in ([], [1, -1], [float("nan")]):
            with self.subTest(taps=taps), self.assertRaises(ValueError):
                response(taps)

    def test_cascade_uses_selected_conditional_event_grid_and_stage_lag(self):
        flatness, lp = [1, 1], [1]
        acv = cascade_response(flatness, lp, "acv", points=3)
        aci = cascade_response(flatness, lp, "aci", points=3)
        acv_rate = CONDITIONAL_G3_HZ / CONDITIONAL_ACV_EVENT_PERIOD_G3
        aci_rate = CONDITIONAL_G3_HZ / CONDITIONAL_ACI_EVENT_PERIOD_G3
        self.assertEqual(acv[0], (0.0, 0.0))
        self.assertAlmostEqual(acv[-1][0], acv_rate / 2)
        self.assertAlmostEqual(aci[-1][0], aci_rate / 2)
        # The stage-one even lag cancels at event Nyquist; odd lag does not.
        self.assertEqual(acv[-1][1], 0.0)
        self.assertLess(aci[-1][1], -300.0)
        with self.assertRaises(ValueError):
            cascade_response(flatness, lp, "auto")


if __name__ == "__main__":
    unittest.main()
