"""Read-only Tk view of physical CAL slots and their stored-value differences."""
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .cal_history import compare_slots
from .cal_viewer import CalViewer


class CalHistoryViewer(tk.Toplevel):
    """Inspect one saved NOR image's CAL slots without implying chronology."""

    def __init__(self, parent, path: str, history: dict):
        super().__init__(parent)
        self.title(f'CAL history — {Path(path).name}')
        self.geometry('1160x780')
        self.minsize(820, 540)
        self.path = path
        self.history = history
        self.slots = history.get('slots', [])
        self.by_id = {slot['id']: slot for slot in self.slots}
        self.comparable_ids = [slot['id'] for slot in self.slots if slot.get('comparable')]

        ttk.Label(self, text=f'{Path(path).name}  |  {len(self.slots)} physical CAL slots',
                  padding=(10, 10, 10, 2)).pack(anchor='w')
        ttk.Label(self, text='Slots are in physical NOR order, not calendar order. '
                  'Current means marked by this saved dump, not live instrument state.',
                  padding=(10, 0, 10, 4), wraplength=1100).pack(anchor='w')
        if history.get('selectionNote'):
            ttk.Label(self, text=history['selectionNote'], padding=(10, 0, 10, 8),
                      wraplength=1100).pack(anchor='w')

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True, padx=10, pady=5)
        slots_tab = ttk.Frame(self.tabs, padding=8)
        changes_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(slots_tab, text='Slots')
        self.tabs.add(changes_tab, text='Changes')
        self._slots_ui(slots_tab)
        self._changes_ui(changes_tab)

    def _slots_ui(self, frame):
        ttk.Label(frame, text='All physical slots remain visible. Incomplete or invalid '
                  'slots cannot be decoded or compared.', wraplength=1000).pack(anchor='w', pady=(0, 7))
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill='both', expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = ('slot', 'offset', 'state', 'status', 'schema', 'checksum', 'hash', 'duplicate')
        self.slots_table = ttk.Treeview(table_frame, columns=columns, show='headings',
                                        selectmode='browse')
        specs = [('slot', 'Slot', 75), ('offset', 'NOR offset', 100),
                 ('state', 'State', 95), ('status', 'Status', 165),
                 ('schema', 'Schema', 70), ('checksum', 'Checksum', 95),
                 ('hash', 'Body SHA-256', 310), ('duplicate', 'Duplicate of', 100)]
        for key, title, width in specs:
            self.slots_table.heading(key, text=title)
            self.slots_table.column(key, width=width, minwidth=55)
        self.slots_table.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.slots_table.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.slots_table.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(table_frame, orient='horizontal', command=self.slots_table.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.slots_table.configure(xscrollcommand=horizontal.set)
        for slot in self.slots:
            current = '  (Current)' if slot['id'] == self.history.get('currentSlot') else ''
            checksum = slot.get('checksumValid')
            values = (slot['id'] + current, f"0x{slot['norOffset']:X}", slot['state'],
                      slot['status'], slot.get('version') if slot.get('version') is not None else '—',
                      'OK' if checksum is True else 'Mismatch' if checksum is False else '—',
                      slot.get('bodySha256') or '—', slot.get('duplicateOf') or '—')
            self.slots_table.insert('', 'end', iid=slot['id'], values=values)
        self.slots_table.bind('<<TreeviewSelect>>', self._slot_selected)
        self.slots_table.bind('<Double-1>', self._open_slot)
        footer = ttk.Frame(frame)
        footer.pack(fill='x', pady=(8, 0))
        self.slot_note = ttk.Label(footer, text='Select a slot to inspect its status.', wraplength=850)
        self.slot_note.pack(side='left', fill='x', expand=True)
        self.open_button = ttk.Button(footer, text='Inspect selected CAL', command=self._open_slot)
        self.open_button.pack(side='right')
        self.open_button.state(['disabled'])

    def _slot_selected(self, *_):
        selected = self.slots_table.selection()
        slot = self.by_id.get(selected[0]) if selected else None
        if slot is None:
            self.slot_note.configure(text='Select a slot to inspect its status.')
            self.open_button.state(['disabled'])
            return
        if slot.get('comparable') and slot.get('report') is not None:
            self.slot_note.configure(text=f"{slot['id']}: decoded CAL available. "
                                     'The saved values can be inspected read-only.')
            self.open_button.state(['!disabled'])
        else:
            self.slot_note.configure(text=f"{slot['id']}: {slot['status']}. "
                                     + (slot.get('issue', '') + ' ' if slot.get('issue') else '') +
                                     'No decoded CAL view is available for this slot.')
            self.open_button.state(['disabled'])

    def _open_slot(self, *_):
        selected = self.slots_table.selection()
        slot = self.by_id.get(selected[0]) if selected else None
        if slot and slot.get('comparable') and slot.get('report') is not None:
            CalViewer(self, f"{self.path} [{slot['id']}]", slot['report'])

    def _changes_ui(self, frame):
        bar = ttk.Frame(frame)
        bar.pack(fill='x', pady=(0, 7))
        ttk.Label(bar, text='Reference').pack(side='left')
        current = self.history.get('currentSlot') or self.history.get('fallbackSlot')
        reference = current if current in self.comparable_ids else next(iter(self.comparable_ids), '')
        target = next((id_ for id_ in self.comparable_ids if id_ != reference), '')
        self.reference = tk.StringVar(value=reference)
        self.selected = tk.StringVar(value=target)
        self.reference_box = ttk.Combobox(bar, textvariable=self.reference, state='readonly',
                                          values=self.comparable_ids, width=10)
        self.reference_box.pack(side='left', padx=(5, 16))
        ttk.Label(bar, text='Selected').pack(side='left')
        self.selected_box = ttk.Combobox(bar, textvariable=self.selected, state='readonly',
                                         values=self.comparable_ids, width=10)
        self.selected_box.pack(side='left', padx=5)
        filters = ttk.Frame(frame)
        filters.pack(fill='x', pady=(0, 7))
        self.changed_only = tk.BooleanVar(value=True)
        ttk.Checkbutton(filters, text='Changed only', variable=self.changed_only,
                        command=self._refresh_changes).pack(side='left')
        ttk.Label(filters, text='Search').pack(side='left', padx=(20, 5))
        self.search = tk.StringVar()
        ttk.Entry(filters, textvariable=self.search, width=36).pack(side='left')
        self.change_count = ttk.Label(filters)
        self.change_count.pack(side='right')
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill='both', expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.changes_table = ttk.Treeview(table_frame,
                                          columns=('parameter', 'reference', 'selected', 'delta'),
                                          show='headings', selectmode='browse')
        for key, title, width in [('parameter', 'Parameter', 370), ('reference', 'Reference', 210),
                                  ('selected', 'Selected', 210), ('delta', 'Raw delta', 190)]:
            self.changes_table.heading(key, text=title)
            self.changes_table.column(key, width=width, minwidth=65)
        self.changes_table.tag_configure('changed', background='#fff2ce')
        self.changes_table.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.changes_table.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.changes_table.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(table_frame, orient='horizontal', command=self.changes_table.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.changes_table.configure(xscrollcommand=horizontal.set)
        self.change_note = ttk.Label(frame, text='Comparisons use stored values and raw bytes; '
                                     'a changed marker does not judge calibration correctness.',
                                     wraplength=1000)
        self.change_note.pack(anchor='w', pady=(7, 0))
        self.raw_detail = ttk.Label(frame, text='', wraplength=1050)
        self.raw_detail.pack(anchor='w', pady=(4, 0))
        self.comparison_rows = []
        self.changes_table.bind('<<TreeviewSelect>>', self._change_selected)
        self.reference.trace_add('write', self._refresh_changes)
        self.selected.trace_add('write', self._refresh_changes)
        self.search.trace_add('write', self._refresh_changes)
        self._refresh_changes()

    def _refresh_changes(self, *_):
        self.changes_table.delete(*self.changes_table.get_children())
        self.comparison_rows = []
        self.raw_detail.configure(text='')
        reference, selected = self.reference.get(), self.selected.get()
        if reference not in self.comparable_ids or selected not in self.comparable_ids:
            self.change_count.configure(text='0 values')
            self.change_note.configure(text='Choose two comparable slots to inspect stored CAL changes.')
            return
        rows = compare_slots(self.by_id[reference], self.by_id[selected])
        self.comparison_rows = rows
        query = self.search.get().strip().casefold()
        visible = 0
        changed = sum(bool(row['changed']) for row in rows)
        for index, row in enumerate(rows):
            if self.changed_only.get() and not row['changed']:
                continue
            label = row.get('title') or row['name']
            if query and query not in (row['name'] + ' ' + label).casefold():
                continue
            marker = '* ' if row['changed'] else ''
            self.changes_table.insert('', 'end', iid=str(index),
                                      values=(marker + label, row['reference'], row['selected'],
                                              row['delta']),
                                      tags=('changed',) if row['changed'] else ())
            visible += 1
        self.change_count.configure(text=f'{visible} shown / {changed} changed / {len(rows)} values')
        self.change_note.configure(text='* marks a raw stored-value change, including distinct '
                                   'floating-point encodings. Physical slot order does not establish '
                                   'when the change occurred or whether a value is correct.')

    def _change_selected(self, *_):
        selection = self.changes_table.selection()
        if not selection:
            return
        row = self.comparison_rows[int(selection[0])]
        self.raw_detail.configure(text=f"{row['name']} — stored reference: {row['referenceRaw']}; "
                                  f"stored selected: {row['selectedRaw']}. "
                                  f"Bytes: {row['referenceHex']} → {row['selectedHex']}. "
                                  'Raw delta = selected minus reference, in stored units.')
