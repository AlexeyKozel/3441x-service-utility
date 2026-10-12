"""Read-only trend calculations and a small Tk canvas for CAL slot values."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Any

from .cal_engine import coefficient_choices, _finite_number, scalar_change


def calculate_trend(history: dict, field_name: str, reference_slot: str) -> dict:
    """Calculate per-slot deltas; points retain physical index and are never joined."""
    slots = history.get('slots', [])
    by_id = {slot.get('id'): slot for slot in slots}
    reference = by_id.get(reference_slot)
    if not reference or not reference.get('comparable') or not isinstance(reference.get('report'), dict):
        return {'available': False, 'reason': 'Reference slot has no valid decoded CAL record.',
                'points': [], 'unit': ''}
    ref_row = next((row for row in reference['report'].get('schema45', {}).get('values', [])
                    if row.get('name') == field_name), None)
    ref_value = _finite_number(ref_row.get('value')) if ref_row else None
    if ref_value is None:
        return {'available': False, 'reason': 'Reference value is missing, invalid, or non-finite.',
                'points': [], 'unit': ''}
    family = ref_row.get('meaning', {}).get('family', '')
    is_divider = family == 'Divider10M'
    if not is_divider and ref_value == 0:
        return {'available': False,
                'reason': 'Relative change is unavailable because the reference value is zero.',
                'points': [], 'unit': 'ppm'}
    points = []
    for physical_index, slot in enumerate(slots):
        index = slot.get('index', physical_index)
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < 32:
            continue
        if not slot.get('comparable') or not isinstance(slot.get('report'), dict):
            continue
        row = next((item for item in slot['report'].get('schema45', {}).get('values', [])
                    if item.get('name') == field_name), None)
        value = _finite_number(row.get('value')) if row else None
        if value is None:
            continue
        y = scalar_change(ref_value, value, 'ohm_delta' if is_divider else 'ppm')
        if y is not None:
            points.append({'index': index, 'slot': slot.get('id', str(index)),
                           'value': value, 'y': y})
    return {'available': True, 'reason': '', 'referenceValue': ref_value,
            'points': points, 'unit': 'ohm' if is_divider else 'ppm',
            'mode': 'ohm_delta' if is_divider else 'ppm'}


class CalHistoryPlot(ttk.Frame):
    """Canvas scatter plot of saved CAL values by physical NOR slot index."""

    def __init__(self, parent, history: dict, reference: tk.StringVar):
        super().__init__(parent)
        self.history = history
        self.reference = reference
        self.choices = coefficient_choices(history)
        self.choice_by_label = {item['label']: item for item in self.choices}
        initial = next((item for item in self.choices if item['mode'] == 'ohm_delta'),
                       self.choices[0] if self.choices else None)
        self.coefficient = tk.StringVar(value=initial['label'] if initial else '')

        controls = ttk.Frame(self)
        controls.pack(fill='x', pady=(0, 7))
        ttk.Label(controls, text='Coefficient').pack(side='left')
        self.coefficient_box = ttk.Combobox(
            controls, textvariable=self.coefficient, state='readonly', width=58,
            values=[item['label'] for item in self.choices])
        self.coefficient_box.pack(side='left', padx=(5, 16))
        ttk.Label(controls, text='Reference slot').pack(side='left')
        self.reference_box = ttk.Combobox(
            controls, textvariable=self.reference, state='readonly', width=10,
            values=[slot['id'] for slot in history.get('slots', []) if slot.get('comparable')])
        self.reference_box.pack(side='left', padx=5)
        self.status = ttk.Label(self, text='', wraplength=1000)
        self.status.pack(fill='x', pady=(0, 5))
        self.canvas = tk.Canvas(self, background='white', highlightthickness=1,
                                highlightbackground='#b8b8b8', height=390)
        self.canvas.pack(fill='both', expand=True)
        ttk.Label(self, text='X positions are physical NOR slots. Empty, invalid, incomplete, '
                  'or undecodable slots remain gaps; points are not connected. No calendar drift '
                  'is inferred.', wraplength=1000).pack(anchor='w', pady=(6, 0))
        self.coefficient.trace_add('write', self.redraw)
        self.reference.trace_add('write', self.redraw)
        self.canvas.bind('<Configure>', self.redraw)
        self.redraw()

    def redraw(self, *_):
        canvas = self.canvas
        canvas.delete('all')
        choice = self.choice_by_label.get(self.coefficient.get())
        if choice is None:
            self.status.configure(text='No interpreted scale/gain fields are available in the decoded CAL slots.')
            return
        trend = calculate_trend(self.history, choice['name'], self.reference.get())
        if not trend['available']:
            self.status.configure(text=trend['reason'])
            return
        title = choice['title']
        if trend['mode'] == 'ohm_delta':
            self.status.configure(text=f'{title} [{choice["name"]}]: selected value minus reference, in ohms. '
                                   f'Reference {self.reference.get()} = {trend["referenceValue"]:.8g} ohm.')
            ylabel = 'Change (ohm)'
        else:
            self.status.configure(text=f'{title} [{choice["name"]}]: relative change from '
                                   f'{self.reference.get()}, in ppm. Reference value = '
                                   f'{trend["referenceValue"]:.8g}.')
            ylabel = 'Relative change (ppm)'
        points = trend['points']
        if not points:
            self.status.configure(text=self.status.cget('text') + ' No finite values are available to plot.')
            return
        self._draw(points, ylabel)

    def _draw(self, points: list[dict], ylabel: str):
        canvas = self.canvas
        width, height = max(canvas.winfo_width(), 360), max(canvas.winfo_height(), 260)
        left, right, top, bottom = 76, width - 24, 22, height - 48
        if right <= left or bottom <= top:
            return
        ys = [point['y'] for point in points]
        low, high = min(ys), max(ys)
        if low == high:
            padding = abs(low) * 0.08 or 1.0
        else:
            padding = (high - low) * 0.08
        low, high = low - padding, high + padding
        xcoord = lambda index: left + index * (right - left) / 31
        ycoord = lambda value: bottom - (value - low) * (bottom - top) / (high - low)
        for step in range(5):
            value = low + (high - low) * step / 4
            y = ycoord(value)
            canvas.create_line(left, y, right, y, fill='#e2e5e8')
            canvas.create_text(left - 8, y, text=f'{value:.5g}', anchor='e', fill='#40464d')
        canvas.create_line(left, top, left, bottom, fill='#50565c')
        canvas.create_line(left, bottom, right, bottom, fill='#50565c')
        for index in range(0, 32, 4):
            x = xcoord(index)
            canvas.create_line(x, bottom, x, bottom + 4, fill='#50565c')
            canvas.create_text(x, bottom + 7, text=f"{'A' if index < 16 else 'B'}{index % 16}", anchor='n', fill='#40464d')
        canvas.create_text((left + right) / 2, height - 8, text='Physical CAL slot (not calendar time)', anchor='s')
        canvas.create_text(15, (top + bottom) / 2, text=ylabel, angle=90)
        for point in points:
            x, y = xcoord(point['index']), ycoord(point['y'])
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4,
                               fill='#1769aa', outline='white', width=1,
                               tags=(f"slot-{point['slot']}",))
            canvas.tag_bind(f"slot-{point['slot']}", '<Enter>',
                            lambda event, p=point: self.status.configure(
                                text=f"Slot {p['slot']} (physical index {p['index']}): {p['y']:.8g} {ylabel.lower()}"))
