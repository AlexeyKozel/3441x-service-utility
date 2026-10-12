"""Pure comparison checks for the saved CAL filter overlay."""
from __future__ import annotations

import sys
import unittest
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utility3441x.cal_filter_compare import (  # noqa: E402
    CASCADE_MODE,
    COEFFICIENT_MODE,
    compare_filter_curves,
    FilterComparison,
)


def explained_report(*, flatness_delta: int = 0, lp_delta: int = 0) -> dict:
    values = []
    for name, family, delta in (
        ('Acv100mVFlatnessCoefs', 'flatness', flatness_delta),
        ('AcvLpFilter', 'lp', lp_delta),
    ):
        for index in range(70):
            # Nonzero DC sum, with one controlled change for comparison tests.
            raw = 2 + (delta if index == 1 else 0)
            values.append({
                'type': 'int32', 'value': raw,
                'meaning': {'family': family, 'nameBase': name, 'elementIndex': index},
            })
    while len(values) < 1072:
        values.append({'type': 'int32', 'value': 0,
                       'meaning': {'family': 'other', 'nameBase': 'Other',
                                   'elementIndex': len(values)}})
    return {'version': 45, 'bodyLength': 4924,
            'interpretation': {'status': 'available'},
            'schema45': {'elementCount': 1072, 'values': values}}


class CalFilterCompareTests(unittest.TestCase):
    def test_gui_switches_model_and_rejects_invalid_zoom(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(root.destroy)
        root.withdraw()
        view = FilterComparison(root, explained_report(), explained_report(flatness_delta=3),
                                'A0', 'A1')
        view.withdraw()
        root.update()
        self.assertTrue(view.visible)
        view.mode.set(CASCADE_MODE)
        root.update()
        self.assertEqual(view.comparison.x_label, 'Nominal frequency (Hz)')
        self.assertTrue(all('Flatness' in name for name in view.vector_box['values']))
        self.assertTrue(view.visible)
        view.max_x.set('nan')
        view._draw()
        self.assertFalse(view.visible)
        self.assertIn('positive maximum', view.canvas.itemcget(view.canvas.find_all()[0], 'text'))

    def test_identical_input_produces_identical_curves_and_shared_x(self):
        report = explained_report()
        compared = compare_filter_curves(report, report, 'Acv100mVFlatnessCoefs',
                                         COEFFICIENT_MODE, points=33)
        self.assertEqual(compared.reference_curve, compared.selected_curve)
        self.assertEqual([x for x, _ in compared.reference_curve],
                         [x for x, _ in compared.selected_curve])
        self.assertIn('not Hz', compared.x_label)

    def test_changed_vector_changes_projection_without_changing_x_grid(self):
        compared = compare_filter_curves(
            explained_report(), explained_report(flatness_delta=3),
            'Acv100mVFlatnessCoefs', COEFFICIENT_MODE, points=65)
        self.assertNotEqual(compared.reference_curve, compared.selected_curve)
        self.assertEqual(tuple(x for x, _ in compared.reference_curve),
                         tuple(x for x, _ in compared.selected_curve))

    def test_nominal_hz_comparison_uses_same_cascade_grid_and_includes_lp(self):
        reference = explained_report()
        identical = compare_filter_curves(reference, reference,
                                          'Acv100mVFlatnessCoefs', CASCADE_MODE, points=17)
        changed_lp = compare_filter_curves(reference, explained_report(lp_delta=7),
                                           'Acv100mVFlatnessCoefs', CASCADE_MODE, points=17)
        self.assertEqual(identical.reference_curve, identical.selected_curve)
        self.assertNotEqual(changed_lp.reference_curve, changed_lp.selected_curve)
        self.assertEqual(tuple(x for x, _ in changed_lp.reference_curve),
                         tuple(x for x, _ in changed_lp.selected_curve))
        self.assertEqual(changed_lp.reference_curve[-1][0], identical.reference_curve[-1][0])
        self.assertIn('Conditional ACV', changed_lp.scope)
        self.assertIn('not identify the active instrument configuration', changed_lp.scope)

    def test_invalid_model_and_unpaired_cascade_vector_are_rejected(self):
        report = explained_report()
        with self.assertRaises(ValueError):
            compare_filter_curves(report, report, 'Acv100mVFlatnessCoefs', 'unknown')
        with self.assertRaises(ValueError):
            compare_filter_curves(report, report, 'AcvLpFilter', CASCADE_MODE)


if __name__ == '__main__':
    unittest.main()
