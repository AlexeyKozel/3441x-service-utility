"""Read-only overlay of two saved CAL filter projections.

The curves share one extracted vector and one x grid. They are coefficient
math only, or the conditional APP11 2.43 image1 nominal-Hz cascade model; they
do not represent a measured or complete instrument response.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import tkinter as tk
from tkinter import ttk
from typing import Any

from .cal_filters import cascade_response, filter_vectors, response


COEFFICIENT_MODE = 'Coefficient index'
CASCADE_MODE = 'APP11 2.43 image1 cascade (nominal Hz)'
MODES = (COEFFICIENT_MODE, CASCADE_MODE)


@dataclass(frozen=True)
class FilterCurveComparison:
    vector_name: str
    mode: str
    x_label: str
    reference_curve: tuple[tuple[float, float], ...]
    selected_curve: tuple[tuple[float, float], ...]
    scope: str


def common_filter_vectors(reference_report: dict[str, Any],
                          selected_report: dict[str, Any]) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """Extract vectors and return each report's vectors with common names only."""
    reference = filter_vectors(reference_report)
    selected = filter_vectors(selected_report)
    common = set(reference) & set(selected)
    if not common:
        raise ValueError('The saved CAL reports have no matching complete FIR vectors.')
    return ({name: reference[name] for name in reference if name in common},
            {name: selected[name] for name in selected if name in common})


def compare_filter_curves(reference_report: dict[str, Any],
                          selected_report: dict[str, Any], vector_name: str,
                          mode: str = COEFFICIENT_MODE, *, points: int | None = None
                          ) -> FilterCurveComparison:
    """Compute two projections for one identically named vector and x grid."""
    reference, selected = common_filter_vectors(reference_report, selected_report)
    if vector_name not in reference:
        raise ValueError(f'No complete matching FIR vector named {vector_name}.')
    if mode == COEFFICIENT_MODE:
        sample_count = 2049 if points is None else points
        first = response(reference[vector_name], points=sample_count)
        second = response(selected[vector_name], points=sample_count)
        x_label = 'Cycles per coefficient-index step (not Hz)'
        scope = ('Single-vector polynomial; signed low16 operands, DC normalized. '
                 'Coefficient-index frequency is not a sample rate or a physical frequency.')
    elif mode == CASCADE_MODE:
        if 'FlatnessCoefs' not in vector_name:
            raise ValueError('Nominal-Hz cascade comparison requires a flatness vector.')
        kind = 'acv' if vector_name.startswith('Acv') else 'aci' if vector_name.startswith('Aci') else None
        if kind is None:
            raise ValueError('Cannot identify the ACV or ACI cascade for this flatness vector.')
        lp_name = 'AcvLpFilter' if kind == 'acv' else 'AciLpFilter'
        if lp_name not in reference or lp_name not in selected:
            raise ValueError(f'Paired {lp_name} vector is unavailable in one saved CAL report.')
        sample_count = 4097 if points is None else points
        first = cascade_response(reference[vector_name], reference[lp_name], kind,
                                 points=sample_count)
        second = cascade_response(selected[vector_name], selected[lp_name], kind,
                                  points=sample_count)
        x_label = 'Nominal frequency (Hz)'
        conditions = ('72 G3/event; lags 2k/j; banks 68/138/68/68; L/K/H=71/59/63'
                      if kind == 'acv' else
                      '108 G3/event; lags 7k/j; banks 68/488/68/68; L/K/H=107/102/92')
        scope = (f'Conditional {kind.upper()} flatness × LP; APP11 2.43 image1, nominal '
                 f'G3=106.25 MHz; {conditions}; FineTrigger=2. Assumes held lock/release '
                 'and no new RX writes after washout. This preset does not identify the '
                 'active instrument configuration.')
    else:
        raise ValueError(f'Unknown filter projection mode: {mode}.')

    if len(first) != len(second) or any(a[0] != b[0] for a, b in zip(first, second)):
        raise ValueError('The two projections do not share the same x-coordinate grid.')
    return FilterCurveComparison(vector_name, mode, x_label, tuple(first), tuple(second), scope)


class FilterComparison(tk.Toplevel):
    """Overlay two saved CAL reports using a common vector and model."""

    def __init__(self, parent, reference_report: dict[str, Any], selected_report: dict[str, Any],
                 reference_label: str, selected_label: str):
        super().__init__(parent)
        self.title('CAL filter comparison')
        self.geometry('1120x760')
        self.minsize(820, 540)
        self.reference_report = reference_report
        self.selected_report = selected_report
        self.reference_label = str(reference_label)
        self.selected_label = str(selected_label)
        self.comparison: FilterCurveComparison | None = None
        self.visible: list[tuple[float, float, float]] = []

        ttk.Label(self, text=f'Reference: {self.reference_label}    |    Selected: {self.selected_label}',
                  padding=(10, 9, 10, 3), wraplength=1080).pack(anchor='w')
        self.integrity = ttk.Label(self, text=self._integrity_text(), padding=(10, 0, 10, 4),
                                   wraplength=1080)
        self.integrity.pack(anchor='w')

        try:
            self.reference_vectors, self.selected_vectors = common_filter_vectors(
                reference_report, selected_report)
        except ValueError as exc:
            ttk.Label(self, text=f'Filter comparison unavailable: {exc}', padding=12,
                      wraplength=1000).pack(anchor='w')
            return

        self.vector = tk.StringVar()
        self.mode = tk.StringVar(value=COEFFICIENT_MODE)
        self.bar = ttk.Frame(self, padding=(10, 4))
        self.bar.pack(fill='x')
        ttk.Label(self.bar, text='Vector').pack(side='left')
        self.vector_box = ttk.Combobox(self.bar, textvariable=self.vector, state='readonly', width=34)
        self.vector_box.pack(side='left', padx=6)
        ttk.Label(self.bar, text='Model').pack(side='left', padx=(12, 0))
        self.mode_box = ttk.Combobox(self.bar, textvariable=self.mode, state='readonly',
                                     values=MODES, width=39)
        self.mode_box.pack(side='left', padx=6)
        self.scope = ttk.Label(self, wraplength=1080, justify='left', padding=(10, 0, 10, 4))
        self.scope.pack(fill='x')

        zoom = ttk.Frame(self, padding=(10, 2))
        zoom.pack(fill='x')
        self.max_x_label = ttk.Label(zoom)
        self.max_x_label.pack(side='left')
        self.max_x = tk.StringVar()
        ttk.Entry(zoom, textvariable=self.max_x, width=14).pack(side='left', padx=6)
        ttk.Button(zoom, text='Apply', command=self._draw).pack(side='left')
        self.canvas = tk.Canvas(self, background='white', highlightthickness=1,
                                highlightbackground='#cccccc')
        self.canvas.pack(fill='both', expand=True, padx=10, pady=7)
        self.cursor = ttk.Label(self, text='Move the pointer over the plot to read sampled values.',
                                padding=(10, 0, 10, 8))
        self.cursor.pack(anchor='w')
        self.canvas.bind('<Configure>', self._draw)
        self.canvas.bind('<Motion>', self._hover)
        self._update_vectors()

    def _integrity_text(self) -> str:
        def status(report):
            valid = report.get('checksumValid') if isinstance(report, dict) else None
            return 'checksum OK' if valid is True else 'CHECKSUM MISMATCH; values unverified' if valid is False else 'checksum status unavailable'
        return (f'Reference {status(self.reference_report)}; selected {status(self.selected_report)}. '
                'Saved-value comparison only.')

    def _update_vectors(self):
        self._set_vector_values()
        self.mode.trace_add('write', self._mode_changed)
        self.vector.trace_add('write', self._recalculate)
        self._recalculate()

    def _mode_changed(self, *_):
        self._set_vector_values()
        self._recalculate()

    def _set_vector_values(self):
        values = list(self.reference_vectors)
        self.vector_box.configure(values=values)
        flatness = [name for name in values if 'FlatnessCoefs' in name
                    and ((name.startswith('Acv') and 'AcvLpFilter' in values)
                         or (name.startswith('Aci') and 'AciLpFilter' in values))]
        if self.mode.get() == CASCADE_MODE:
            choices = flatness
        else:
            choices = values
        self.vector_box.configure(values=choices)
        if self.vector.get() not in choices:
            self.vector.set(choices[0] if choices else '')

    def _recalculate(self, *_):
        if not hasattr(self, 'canvas'):
            return
        self.max_x.set('')
        self.max_x_label.configure(text=(
            'Maximum cycles per coefficient-index step (blank = full span)'
            if self.mode.get() == COEFFICIENT_MODE else
            'Maximum frequency in Hz (blank = full span)'))
        try:
            self.comparison = compare_filter_curves(
                self.reference_report, self.selected_report, self.vector.get(), self.mode.get())
            integrity = self._integrity_text()
            self.scope.configure(text=f'{integrity}\n{self.comparison.scope} Relative magnitude only, not the full instrument response. '
                                 'Excludes integer truncation/wrap, ADC, analog path, software filters and RMS. '
                                 'Plot floor: −120 dB; narrow nulls depend on sampling resolution.')
        except (ValueError, KeyError) as exc:
            self.comparison = None
            self.scope.configure(text=f'Filter curves unavailable: {exc}')
        self._draw()

    def _draw(self, *_):
        if not hasattr(self, 'canvas'):
            return
        self.canvas.delete('all')
        self.visible = []
        if self.comparison is None:
            return
        curve_a, curve_b = self.comparison.reference_curve, self.comparison.selected_curve
        full_end = curve_a[-1][0]
        try:
            end = float(self.max_x.get()) if self.max_x.get().strip() else full_end
            if not math.isfinite(end) or not 0 < end <= full_end:
                raise ValueError()
        except ValueError:
            unit = 'Hz' if self.mode.get() == CASCADE_MODE else 'cycles per coefficient-index step'
            self.canvas.create_text(20, 20, anchor='nw', text=f'Enter a positive maximum within the full {unit} span.')
            return
        points_a = [(x, max(-120.0, y)) for x, y in curve_a if x <= end]
        points_b = [(x, max(-120.0, y)) for x, y in curve_b if x <= end]
        if len(points_a) < 2 or len(points_b) < 2:
            self.canvas.create_text(20, 20, anchor='nw', text='Span too small for the sampled curves.')
            return
        ys = [y for _, y in points_a + points_b]
        low, high = min(-0.1, min(ys)), max(0.1, max(ys))
        pad = (high - low) * .06
        low, high = low - pad, high + pad
        width, height = max(self.canvas.winfo_width(), 220), max(self.canvas.winfo_height(), 180)
        left, top, right, bottom = 76, 46, width - 24, height - 54

        def position(x, y):
            return left + x / end * (right - left), bottom - (y - low) / (high - low) * (bottom - top)

        for i in range(6):
            x = end * i / 5
            px, _ = position(x, low)
            self.canvas.create_line(px, top, px, bottom, fill='#e5e7eb')
            self.canvas.create_text(px, bottom + 14, text=f'{x:.5g}')
            y = low + (high - low) * i / 5
            _, py = position(0, y)
            self.canvas.create_line(left, py, right, py, fill='#e5e7eb')
            self.canvas.create_text(left - 7, py, anchor='e', text=f'{y:.4g}')
        self.canvas.create_rectangle(left, top, right, bottom, outline='#777777')
        self.canvas.create_text(left, 10, anchor='w', text='Magnitude relative to DC (dB)')
        self.canvas.create_text((left + right) / 2, height - 12, text=self.comparison.x_label)
        self._plot(points_a, position, '#1467b2', ())
        self._plot(points_b, position, '#c43c35', (5, 3))
        self.canvas.create_line(left + 8, 25, left + 34, 25, fill='#1467b2', width=2)
        self.canvas.create_text(left + 40, 25, anchor='w', text=self.reference_label)
        label_x = max(left + 230, width // 2)
        self.canvas.create_line(label_x, 25, label_x + 26, 25, fill='#c43c35', width=2, dash=(5, 3))
        self.canvas.create_text(label_x + 32, 25, anchor='w', text=self.selected_label)
        self.visible = [(a[0], a[1], b[1]) for a, b in zip(curve_a, curve_b) if a[0] <= end]
        self.plot_bounds = left, right, end

    def _plot(self, points, position, color, dash):
        coords = [coordinate for x, y in points for coordinate in position(x, y)]
        self.canvas.create_line(*coords, fill=color, width=2, dash=dash)

    def _hover(self, event):
        if not self.visible:
            return
        left, right, end = self.plot_bounds
        x_guess = min(end, max(0.0, (event.x - left) / (right - left) * end))
        x, reference_db, selected_db = min(self.visible, key=lambda point: abs(point[0] - x_guess))
        unit = 'Hz nominal' if self.mode.get() == CASCADE_MODE else 'cycles/index'
        self.cursor.configure(text=f'{x:.9g} {unit}  |  {self.reference_label}: {reference_db:.9g} dB  |  '
                              f'{self.selected_label}: {selected_db:.9g} dB (sampled)')
