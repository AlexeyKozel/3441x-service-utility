"""Bundled initial APP tables, independent of the opened CAL payload."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk


def load_reference():
    return json.loads((Path(__file__).with_name('data') / 'delay_reference_app11_243.json').read_text(encoding='utf-8'))


class DelayReference(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title('MC / MZ delay reference — 34411A APP 2.43')
        self.geometry('1020x680')
        self.minsize(780, 540)
        self.reference = load_reference()
        ttk.Label(self, text='Initial firmware tables — not values from the opened CAL file or live instrument RAM.',
                  padding=10, wraplength=950).pack(anchor='w')
        ttk.Label(self, text='Saved CAL McDelay/MzDelay have no confirmed numeric link to these tables. '
                  'Nominal time uses 19.952941176 us/count; it is not the complete measurement time.',
                  padding=(10, 0, 10, 8), wraplength=950).pack(anchor='w')
        bar = ttk.Frame(self, padding=10)
        bar.pack(fill='x')
        self.mode = tk.StringVar(value=self.reference['pages'][0]['name'])
        self.nplc = tk.StringVar(value='1')
        ttk.Label(bar, text='Function').pack(side='left')
        ttk.Combobox(bar, textvariable=self.mode, state='readonly', width=24,
                     values=[p['name'] for p in self.reference['pages']]).pack(side='left', padx=8)
        ttk.Label(bar, text='NPLC').pack(side='left')
        ttk.Combobox(bar, textvariable=self.nplc, state='readonly', width=12,
                     values=['All', *[f'{x:g}' for x in self.reference['nplc']]]).pack(side='left', padx=8)
        self.note = ttk.Label(self, wraplength=950, padding=(10, 0, 10, 8))
        self.note.pack(anchor='w')
        frame = ttk.Frame(self, padding=(10, 0))
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = ('nplc', 'range', 'mc', 'mc_ms', 'mz', 'mz_ms')
        self.table = ttk.Treeview(frame, columns=columns, show='headings')
        for key, title, width in zip(columns, ('NPLC', 'Range', 'MC count', 'MC nominal ms', 'MZ count', 'MZ nominal ms'),
                                     (80, 170, 100, 160, 100, 160)):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=65)
        self.table.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(frame, command=self.table.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.table.configure(yscrollcommand=scroll.set)
        ttk.Label(self, padding=10, wraplength=950, justify='left', text=(
            'Application conditions\n'
            'These rows apply to NPLC selection. Explicit aperture uses a different row selector; do not substitute the nearest NPLC.\n'
            'In the software-controlled resistance path, offset compensation at 100 ohm, 1 kohm or 10 kohm uses max(CurrentSrcDelay, MC); '
            'the corresponding wait also takes the maximum with trigger delay.\n'
            'Autozero, sample period and measurement mode affect whether and how MC/MZ waits are applied. '
            'Table entries can be changed in instrument RAM by a service path.')).pack(anchor='w')
        self.mode.trace_add('write', self._refresh)
        self.nplc.trace_add('write', self._refresh)
        self._refresh()

    def _refresh(self, *_):
        page = next(p for p in self.reference['pages'] if p['name'] == self.mode.get())
        self.note.configure(text=('4-wire 10 Mohm, 100 Mohm and 1 Gohm entries are shown as firmware reference only; '
                                  'availability of these range combinations has not been confirmed.'
                                  if page['name'] == 'Resistance 4-wire' else
                                  'Reference settings are selected manually; they do not identify the instrument configuration.'))
        self.table.delete(*self.table.get_children())
        scale_ms = float.fromhex(self.reference['seconds_per_count_hex']) * 1000
        for row, plc in enumerate(self.reference['nplc']):
            if self.nplc.get() != 'All' and self.nplc.get() != f'{plc:g}':
                continue
            for col, label in enumerate(page['ranges']):
                mc, mz = page['mc'][row][col], page['mz'][row][col]
                self.table.insert('', 'end', values=(f'{plc:g}', label, mc, f'{mc*scale_ms:.6f}', mz, f'{mz*scale_ms:.6f}'))
