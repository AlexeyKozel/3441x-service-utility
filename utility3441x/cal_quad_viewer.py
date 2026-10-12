"""Read-only quadratic DCV correction plot, using saved AdcQuad."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk


def quadratic_curve(report: dict, span: float = 10.0) -> list[tuple[float, float]]:
    """Return V0 and added microvolts, limited to the documented +/-10 V example."""
    if not report.get('checksumValid'):
        raise ValueError('A valid CAL checksum is required for the correction plot.')
    if report.get('interpretation', {}).get('status') != 'available':
        raise ValueError('Supported CAL interpretation is required.')
    if not math.isfinite(span) or not 0 < span <= 10:
        raise ValueError('Choose a positive voltage span up to 10 V.')
    matches = [row for row in report.get('schema45', {}).get('values', [])
               if row.get('name') == 'AdcQuad' and row.get('meaning', {}).get('family') == 'AdcQuad']
    if len(matches) != 1:
        raise ValueError('A unique AdcQuad coefficient is required.')
    q = matches[0].get('value')
    if isinstance(q, bool) or not isinstance(q, (int, float)) or not math.isfinite(q):
        raise ValueError('AdcQuad must be finite.')
    points = []
    for i in range(401):
        v = span * (i - 200) / 200
        delta = q * v * v * 1e6
        if not math.isfinite(delta):
            raise ValueError('Quadratic correction overflows the plotted range.')
        points.append((v, delta))
    return points


class QuadraticPlot(ttk.Frame):
    def __init__(self, parent, report):
        super().__init__(parent, padding=8)
        self.report = report
        self.curve = []
        bar = ttk.Frame(self); bar.pack(fill='x')
        ttk.Label(bar, text='Voltage span: ±').pack(side='left')
        self.span = tk.StringVar(value='10')
        ttk.Combobox(bar, textvariable=self.span, values=['0.1', '1', '10'],
                     state='readonly', width=8).pack(side='left', padx=5)
        ttk.Label(bar, text='V').pack(side='left')
        ttk.Label(self, text='DCV quadratic stage: V = V0 + q × V0². '
                  'The graph shows the added correction, not residual instrument error. '
                  'V0 is the voltage before this stage; other CAL and reading guards are not modeled.',
                  wraplength=960, justify='left').pack(fill='x', pady=8)
        self.note = ttk.Label(self, wraplength=960)
        self.note.pack(fill='x')
        self.canvas = tk.Canvas(self, background='white', highlightthickness=1,
                                highlightbackground='#cccccc')
        self.canvas.pack(fill='both', expand=True, pady=8)
        self.cursor = ttk.Label(self, text='Move the pointer over the curve to read the correction.')
        self.cursor.pack(anchor='w')
        self.canvas.bind('<Configure>', self._draw)
        self.canvas.bind('<Motion>', self._hover)
        self.span.trace_add('write', self._refresh)
        self._refresh()

    def _refresh(self, *_):
        self.curve = []
        try:
            self.curve = quadratic_curve(self.report, float(self.span.get()))
            q = next(row['value'] for row in self.report['schema45']['values'] if row['name'] == 'AdcQuad')
            self.note.configure(text=f'Saved AdcQuad q = {q:.12g} 1/V. Read-only calculation.')
        except (ValueError, TypeError, OverflowError) as exc:
            self.note.configure(text=str(exc))
        self.cursor.configure(text='Move the pointer over the curve to read the correction.')
        self._draw()

    def _draw(self, *_):
        c = self.canvas; c.delete('all')
        if not self.curve:
            return
        width, height = max(c.winfo_width(), 300), max(c.winfo_height(), 180)
        left, right, top, bottom = 82, width-24, 28, height-52
        span = self.curve[-1][0]
        low, high = min(y for _, y in self.curve), max(y for _, y in self.curve)
        pad = (high-low)*.08 if high != low else 1.0
        low -= pad; high += pad
        def pos(x, y):
            return left+(x+span)/(2*span)*(right-left), bottom-(y-low)/(high-low)*(bottom-top)
        for i in range(5):
            x = -span+2*span*i/4; y = low+(high-low)*i/4
            px, _ = pos(x, 0); _, py = pos(0, y)
            c.create_line(px,top,px,bottom,fill='#e5e7eb')
            c.create_text(px,bottom+14,text=f'{x:.4g}')
            c.create_line(left,py,right,py,fill='#e5e7eb')
            c.create_text(left-7,py,anchor='e',text=f'{y:.5g}')
        c.create_rectangle(left,top,right,bottom,outline='#777777')
        c.create_text(left,12,anchor='w',text='Added correction (uV)')
        c.create_text((left+right)/2,height-10,text='Voltage before quadratic correction, V0 (V)')
        c.create_line(*[v for x,y in self.curve for v in pos(x,y)],fill='#1467b2',width=2,tags='quadratic')
        self.bounds = left, right, span

    def _hover(self, event):
        if not self.curve or not hasattr(self, 'bounds'):
            return
        left,right,span = self.bounds
        v = max(-span,min(span,(event.x-left)/(right-left)*2*span-span))
        x,y = min(self.curve,key=lambda p:abs(p[0]-v))
        self.cursor.configure(text=f'V0 = {x:.9g} V   |   Added correction = {y:.9g} uV')
