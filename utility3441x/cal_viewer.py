"""Read-only CAL tables and conditional FIR plots for the Tk front end."""
from __future__ import annotations

import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .cal_filters import filter_vectors, response, cascade_response
from .cal_display import build_display
from .cal_delay_reference import DelayReference


class CalViewer(tk.Toplevel):
    def __init__(self, parent, path: str, report: dict):
        super().__init__(parent)
        self.title(f'CAL viewer — {Path(path).name}')
        self.geometry('1120x780')
        self.minsize(850, 580)
        self.report = report
        self.rows = report.get('schema45', {}).get('values', [])
        self.meanings = report.get('schema45', {}).get('meanings', {})
        self.display_rows = build_display(report)
        self.curve = []
        self.x_label = ''
        self.integrity = 'Checksum OK' if report['checksumValid'] else 'CHECKSUM MISMATCH — values unverified'
        ttk.Label(self, text=f'{Path(path).name}  |  Schema {report["version"]}  |  '
                  f'{len(self.rows)} values  |  {self.integrity}', padding=10).pack(anchor='w')
        ttk.Label(self, text='Physical equivalents where established; conditions apply. Stored values remain unchanged.',
                  padding=(10, 0, 10, 8)).pack(anchor='w')
        tabs = ttk.Notebook(self)
        tabs.pack(fill='both', expand=True, padx=10, pady=4)
        values_tab = ttk.Frame(tabs, padding=8)
        filters_tab = ttk.Frame(tabs, padding=8)
        tabs.add(values_tab, text='Calibration values')
        tabs.add(filters_tab, text='Filter curves')
        self._values_ui(values_tab)
        self._filters_ui(filters_tab)
        footer = ttk.Frame(self, padding=8)
        footer.pack(fill='x')
        ttk.Button(footer, text='Export JSON…', command=self._export).pack(side='right')
        ttk.Label(footer, text='Read-only view. Export JSON retains stored values and research details.').pack(side='left')

    def _values_ui(self, frame):
        bar = ttk.Frame(frame)
        bar.pack(fill='x', pady=(0, 8))
        ttk.Label(bar, text='Search').pack(side='left')
        self.search = tk.StringVar()
        ttk.Entry(bar, textvariable=self.search, width=32).pack(side='left', padx=6)
        ttk.Label(bar, text='Family').pack(side='left')
        self.family = tk.StringVar(value='All')
        ttk.Combobox(bar, textvariable=self.family, state='readonly', width=28,
                     values=['All', *sorted(self.meanings)]).pack(side='left', padx=6)
        self.count = ttk.Label(bar)
        self.count.pack(side='right')
        self.technical = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='Show technical details', variable=self.technical,
                        command=self._select).pack(anchor='w', pady=(0, 6))
        split = ttk.Panedwindow(frame, orient='vertical')
        split.pack(fill='both', expand=True)
        table = ttk.Frame(split)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(table, columns=('name', 'value', 'note'),
                                  displaycolumns=('value', 'note'), show='tree headings', selectmode='browse')
        self.table.heading('#0', text='Calibration parameter')
        self.table.column('#0', width=350, minwidth=160)
        for name, title, width in [('name', 'Calibration parameter', 350),
                                   ('value', 'Interpreted value', 270),
                                   ('note', 'Conditions', 340)]:
            self.table.heading(name, text=title)
            self.table.column(name, width=width, minwidth=60)
        self.table.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.table.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.table.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(table, orient='horizontal', command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.table.configure(xscrollcommand=horizontal.set)
        split.add(table, weight=3)
        detail_frame = ttk.Frame(split)
        self.delay_reference_button = ttk.Button(detail_frame, text='Delay reference…',
                                                 command=self._open_delay_reference)
        self.detail = tk.Text(detail_frame, height=10, wrap='word', state='disabled')
        self.detail.tag_configure('delay_reference', foreground='#005eb8', underline=True)
        self.detail.tag_bind('delay_reference', '<Button-1>', lambda event: self._open_delay_reference())
        self.detail.tag_bind('delay_reference', '<Enter>', lambda event: self.detail.configure(cursor='hand2'))
        self.detail.tag_bind('delay_reference', '<Leave>', lambda event: self.detail.configure(cursor='xterm'))
        self.detail.pack(side='left', fill='both', expand=True)
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.detail.yview)
        detail_scroll.pack(side='right', fill='y')
        self.detail.configure(yscrollcommand=detail_scroll.set)
        split.add(detail_frame, weight=1)
        self.table.bind('<<TreeviewSelect>>', self._select)
        self.table.bind('<Button-1>', self._toggle_filter_group)
        self.table.bind('<Double-1>', self._filter_double_click)
        self.search.trace_add('write', self._refresh)
        self.family.trace_add('write', self._refresh)
        self._refresh()

    def _refresh(self, *_):
        self.table.delete(*self.table.get_children())
        self.filter_groups = {}
        query = self.search.get().casefold()
        family = self.family.get()
        matched = 0
        for index, row in enumerate(self.rows):
            key = row.get('meaning', {}).get('family', '')
            display = self.display_rows[index]
            if (query not in (row['name'] + ' ' + key + ' ' + display['title']).casefold()
                    or (family != 'All' and key != family)):
                continue
            parent = ''
            meaning = row.get('meaning', {})
            if key in ('flatness', 'lp') and meaning.get('nameBase') and isinstance(meaning.get('elementIndex'), int):
                parent = 'filter:' + key + ':' + meaning['nameBase']
                if parent not in self.filter_groups:
                    title = display['title'].rsplit(', tap ', 1)[0].replace(' filter tap —', ' filter —')
                    self.filter_groups[parent] = title
                    self.table.insert('', 'end', iid=parent, text=title, open=bool(query) or family != 'All',
                                      values=(title, '', 'Click to expand or collapse'))
            self.table.insert(parent, 'end', iid=str(index), text=display['title'], values=(display['title'], display['value'],
                              display['qualification']))
            matched += 1
        for group in self.filter_groups:
            count = len(self.table.get_children(group))
            self.table.set(group, 'value', f'{count} coefficients' + (' matching' if query else ''))
        children = self.table.get_children()
        self.count.configure(text=f'{matched} / {len(self.rows)} values')
        if children:
            self.table.selection_set(children[0])
            self._select()
        else:
            self.delay_reference_button.pack_forget()
            self._detail('No matching coefficients.')

    def _toggle_filter_group(self, event):
        item = self.table.identify_row(event.y)
        if item in self.filter_groups and self.table.identify_region(event.x, event.y) in ('tree', 'cell'):
            self.table.focus(item)
            self.table.selection_set(item)
            self.table.item(item, open=not bool(self.table.item(item, 'open')))
            self._select()
            return 'break'

    def _filter_double_click(self, event):
        if self.table.identify_row(event.y) in self.filter_groups:
            return 'break'

    def _open_delay_reference(self):
        return DelayReference(self)

    def _detail(self, text, *, delay_reference=False):
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', text)
        if delay_reference:
            label = 'Open delay reference…'
            start = self.detail.search(label, '1.0', stopindex='end')
            if start:
                self.detail.tag_add('delay_reference', start, f'{start}+{len(label)}c')
        self.detail.configure(cursor='xterm')
        self.detail.yview_moveto(0)
        self.detail.configure(state='disabled')

    def _select(self, *_):
        selected = self.table.selection()
        if not selected:
            return
        if selected[0] in self.filter_groups:
            self.delay_reference_button.pack_forget()
            self._detail(self.filter_groups[selected[0]] + '\n\n'
                         'Click this group to expand or collapse its coefficients. '
                         'Select a coefficient to inspect its stored value.\n'
                         'The complete vector defines the filter response; individual taps do not have standalone physical units. '
                         'Use the Filter curves tab to view the response.')
            return
        row = self.rows[int(selected[0])]
        display = self.display_rows[int(selected[0])]
        meaning = row.get('meaning', {})
        card = self.meanings.get(meaning.get('family'), {})
        is_delay = meaning.get('family') in ('McDelay', 'MzDelay')
        self.delay_reference_button.pack_forget()
        if is_delay:
            self.delay_reference_button.pack(side='top', anchor='w', pady=(0, 6), before=self.detail)
        text = [display['title'], display['value']]
        if is_delay:
            text.extend(['', 'Open delay reference…',
                         'Initial APP 2.43 tables by function, range and NPLC; separate from the saved CAL value. '
                         'Their numeric link to this field is not confirmed.'])
        text.extend(['', display['description'], display['qualification'], *display.get('derived', [])])
        if self.technical.get():
            text.extend(['', 'Technical details', row['name'],
                         f'Stored value: {row["value"]!r}  |  {row["type"]}  |  body offset 0x{row["offset"]:04X}',
                         card.get('summary', 'Usage explanation unavailable.'),
                         'Usage evidence: ' + card.get('usage_status', 'unavailable').upper()])
            if meaning.get('elementIndex') is not None:
                text.append(f'Element index: {meaning["elementIndex"]}')
            text.extend(card.get('limitations', []))
            for source in card.get('evidence', []):
                text.append(f'Source: {source["path"]} — {source["scope"]}')
            text.append(f'Body SHA-256: {self.report["bodySha256"]}')
        self._detail('\n'.join(text), delay_reference=is_delay)

    def _filters_ui(self, frame):
        try:
            self.vectors = filter_vectors(self.report)
        except ValueError as exc:
            self.vectors = {}
            ttk.Label(frame, text=f'Filter curves unavailable: {exc}', wraplength=900).pack(anchor='w')
            return
        bar = ttk.Frame(frame)
        bar.pack(fill='x')
        self.vector = tk.StringVar(value=next(iter(self.vectors), ''))
        self.mode = tk.StringVar(value='Coefficient index')
        ttk.Label(bar, text='Vector').pack(side='left')
        ttk.Combobox(bar, textvariable=self.vector, state='readonly', width=30,
                     values=list(self.vectors)).pack(side='left', padx=6)
        ttk.Combobox(bar, textvariable=self.mode, state='readonly', width=35,
                     values=['Coefficient index', 'APP11 2.43 image1 cascade (nominal Hz)']).pack(side='left', padx=6)
        self.scope = ttk.Label(frame, wraplength=960, justify='left')
        self.scope.pack(fill='x', pady=8)
        zoom = ttk.Frame(frame)
        zoom.pack(fill='x')
        ttk.Label(zoom, text='Maximum frequency (blank = full span)').pack(side='left')
        self.max_x = tk.StringVar()
        ttk.Entry(zoom, textvariable=self.max_x, width=14).pack(side='left', padx=6)
        ttk.Button(zoom, text='Apply', command=self._draw).pack(side='left')
        self.canvas = tk.Canvas(frame, background='white', highlightthickness=1,
                                highlightbackground='#cccccc')
        self.canvas.pack(fill='both', expand=True, pady=8)
        self.cursor = ttk.Label(frame, text='Move the pointer over the curve to read a sampled value.')
        self.cursor.pack(anchor='w')
        self.canvas.bind('<Configure>', self._draw)
        self.canvas.bind('<Motion>', self._hover)
        self.vector.trace_add('write', self._recalculate)
        self.mode.trace_add('write', self._recalculate)
        self._recalculate()

    def _recalculate(self, *_):
        self.max_x.set('')
        name = self.vector.get()
        try:
            taps = self.vectors[name]
            if self.mode.get() == 'Coefficient index':
                self.curve = response(taps, points=2049)
                self.x_label = 'Cycles per coefficient-index step (not Hz)'
                note = 'Single-vector polynomial; signed low16 operands, DC normalized. '
            else:
                if 'FlatnessCoefs' not in name:
                    raise ValueError('Select a flatness vector to pair it with the corresponding LP filter.')
                kind = 'ACV' if name.startswith('Acv') else 'ACI'
                lp = self.vectors['AcvLpFilter' if kind == 'ACV' else 'AciLpFilter']
                self.curve = cascade_response(taps, lp, kind.lower(), points=4097)
                self.x_label = 'Nominal frequency (Hz)'
                conditions = ('72 G3/event; lags 2k/j; banks 68/138/68/68; L/K/H=71/59/63'
                              if kind == 'ACV' else
                              '108 G3/event; lags 7k/j; banks 68/488/68/68; L/K/H=107/102/92')
                note = (f'Conditional {kind} flatness × LP; APP11 2.43 image1, nominal G3=106.25 MHz; '
                        f'{conditions}; FineTrigger=2. Assumes held lock/release and no new RX writes after washout. '
                        'This preset does not identify the active instrument configuration. ')
            self.scope.configure(text=f'{self.integrity}. {note} '
                                 'Relative magnitude only, not the full instrument response. '
                                 'Excludes integer truncation/wrap, ADC, analog path, software filters and RMS. '
                                 'Plot floor: −120 dB; narrow nulls depend on sampling resolution.')
        except (ValueError, KeyError) as exc:
            self.curve = []
            self.scope.configure(text=str(exc))
        self._draw()

    def _draw(self, *_):
        canvas = self.canvas
        canvas.delete('all')
        self.visible = []
        if not self.curve:
            return
        try:
            end = float(self.max_x.get()) if self.max_x.get().strip() else self.curve[-1][0]
            if not math.isfinite(end) or not 0 < end <= self.curve[-1][0]:
                raise ValueError()
        except ValueError:
            canvas.create_text(20, 20, anchor='nw', text='Enter a positive maximum within the full frequency span.')
            return
        points = [(x, max(-120.0, y)) for x, y in self.curve if x <= end]
        if len(points) < 2:
            canvas.create_text(20, 20, anchor='nw', text='Span too small for this sampled curve.')
            return
        width, height = max(canvas.winfo_width(), 200), max(canvas.winfo_height(), 160)
        left, top, right, bottom = 72, 24, width - 24, height - 55
        low = min(-0.1, min(y for _, y in points))
        high = max(0.1, max(y for _, y in points))
        pad = (high - low) * .06
        low, high = low - pad, high + pad
        def position(x, y):
            return left + x / end * (right-left), bottom - (y-low)/(high-low)*(bottom-top)
        for i in range(6):
            x = end * i/5
            px, _ = position(x, low)
            canvas.create_line(px, top, px, bottom, fill='#e5e7eb')
            canvas.create_text(px, bottom+14, text=f'{x:.5g}')
            y = low + (high-low)*i/5
            _, py = position(0, y)
            canvas.create_line(left, py, right, py, fill='#e5e7eb')
            canvas.create_text(left-7, py, anchor='e', text=f'{y:.4g}')
        canvas.create_rectangle(left, top, right, bottom, outline='#777777')
        canvas.create_text(left, 10, anchor='w', text='Magnitude relative to DC (dB)')
        canvas.create_text((left+right)/2, height-12, text=self.x_label)
        coords = [v for x, y in points for v in position(x, y)]
        canvas.create_line(*coords, fill='#1467b2', width=2, tags='response')
        self.visible = [(x,y) for x,y in self.curve if x <= end]
        self.plot_bounds = left, right, end

    def _hover(self, event):
        if not getattr(self, 'visible', []):
            return
        left, right, end = self.plot_bounds
        frequency = min(end, max(0, (event.x-left)/(right-left)*end))
        x, y = min(self.visible, key=lambda point: abs(point[0]-frequency))
        self.cursor.configure(text=f'{x:.9g} {"Hz (nominal)" if self.mode.get() != "Coefficient index" else "cycles/index"}   |   {y:.9g} dB (sampled)')

    def _export(self):
        path = filedialog.asksaveasfilename(parent=self, title='Export decoded CAL JSON',
                                          defaultextension='.json', filetypes=[('JSON', '*.json')])
        if path:
            try:
                Path(path).write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            except OSError as exc:
                messagebox.showerror('Export CAL', str(exc), parent=self)
