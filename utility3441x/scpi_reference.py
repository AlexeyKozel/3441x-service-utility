"""Offline, evidence-scoped reference for undocumented firmware commands."""
from __future__ import annotations

import json
from pathlib import Path


def load_reference() -> dict:
    path = Path(__file__).with_name('data') / 'scpi_reference_v1.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 'scpi_reference.v1':
        raise ValueError('Unsupported SCPI reference schema')
    return data


def search_commands(data: dict, query: str = '', form: str = 'All',
                    technical: bool = False) -> list[dict]:
    """Search card content by default; include catalog-only fields on request."""
    words = query.casefold().split()
    found = []
    for row in data['commands']:
        if form != 'All' and row['form'] != form:
            continue
        searchable = command_text(row)
        if technical:
            searchable += '\n' + json.dumps(row, ensure_ascii=False)
        if all(word in searchable.casefold() for word in words):
            found.append(row)
    return found


def _text(value) -> str:
    if isinstance(value, list):
        return '\n'.join('- ' + _text(item) for item in value)
    if isinstance(value, dict):
        return '\n'.join(str(key).replace('_', ' ').capitalize() + ': ' + _text(item) for key, item in value.items())
    return str(value)


def command_text(row: dict, technical: bool = False) -> str:
    """Render the full card text; the default is retained for CLI compatibility."""
    lines = [row['syntax'], row.get('summary', ''), '',
             'Form: ' + row['form'], 'Static analysis: ' + row['level'].replace('_', ' ').lower()]
    for key, title in (
        ('aliases', 'Registered spellings'),
        ('documentation', 'Documentation scope'),
        ('parameters', 'Parameters and response'),
        ('selectors', 'Selectors and results'),
        ('handler', 'Firmware handler'),
        ('trace', 'Execution path'),
        ('conditions', 'Conditions and errors'),
        ('effects', 'What it reads or changes'),
        ('persistence', 'Persistence and activation'),
        ('applicability', 'APP and model applicability'),
        ('related', 'Related CAL and firmware nodes'),
        ('open', 'Unresolved parts'),
    ):
        value = row.get(key)
        if value:
            lines.extend(['', title, _text(value)])
    if technical:
        for key in ('grammar', 'registration', 'evidence'):
            if row.get(key):
                title = 'Registration grammar (initial extraction)' if key == 'grammar' else key.title()
                if key == 'grammar':
                    lines.extend(['', title,
                                  'Historical extraction; may be superseded. Current syntax and unresolved-parts notes take precedence.',
                                  _text(row[key])])
                else:
                    lines.extend(['', title, _text(row[key])])
    return '\n'.join(lines)


def _common_card_text(row: dict, technical: bool = False) -> str:
    """Compact GUI card that leaves selector payloads to the selector chooser."""
    without_selectors = {**row, 'selectors': [], 'grammar': {}}
    return command_text(without_selectors, technical=technical)


def _selector_label(selector: dict) -> str:
    meaning = selector.get('meaning', '')
    return f"{selector.get('selector', '?')} — {meaning}" if meaning else str(selector.get('selector', '?'))


def _selector_text(selector: dict) -> str:
    # Keep every reviewed field, including limits and selector-specific caveats.
    return _text(selector)


def reference_report(query: str = '', technical: bool = False) -> dict:
    data = load_reference()
    return {**data, 'commands': search_commands(data, query, technical=technical)}


def build_reference_tab(parent, navigate_topic=None):
    # Tk is imported only for GUI use. No transport or instrument object is used.
    import tkinter as tk
    from tkinter import ttk

    data = load_reference()
    frame = ttk.Frame(parent, padding=8)
    ttk.Label(frame, text='Hidden SCPI reference — static firmware analysis; no command execution.',
              wraplength=950).pack(anchor='w')
    ttk.Label(frame, text=data['scope'], wraplength=950).pack(anchor='w', pady=(3, 8))
    bar = ttk.Frame(frame)
    bar.pack(fill='x')
    ttk.Label(bar, text='Search').pack(side='left')
    search = tk.StringVar()
    ttk.Entry(bar, textvariable=search, width=38).pack(side='left', padx=6)
    form = tk.StringVar(value='All')
    ttk.Combobox(bar, textvariable=form, state='readonly', width=16,
                 values=['All', *sorted({r['form'] for r in data['commands']})]).pack(side='left')
    count = ttk.Label(bar)
    count.pack(side='right')

    options = ttk.Frame(frame)
    options.pack(fill='x', pady=(4, 0))
    technical_search = tk.BooleanVar(value=False)
    technical = tk.BooleanVar(value=False)
    historical = tk.BooleanVar(value=False)
    ttk.Checkbutton(options, text='Search technical catalogue fields', variable=technical_search).pack(side='left')
    ttk.Checkbutton(options, text='Show evidence and registration details', variable=technical).pack(side='left', padx=(12, 0))
    ttk.Checkbutton(options, text='Show historical registration grammar', variable=historical).pack(side='left', padx=(12, 0))

    split = ttk.Panedwindow(frame, orient='vertical')
    split.pack(fill='both', expand=True, pady=6)
    top = ttk.Frame(split)
    table = ttk.Treeview(top, columns=('command', 'form', 'summary'), show='headings',
                         selectmode='browse', height=7)
    for name, title, width in [('command', 'Command', 290), ('form', 'Form', 85),
                                ('summary', 'Behavior', 510)]:
        table.heading(name, text=title)
        table.column(name, width=width, anchor='w')
    table.pack(side='left', fill='both', expand=True)
    scroll = ttk.Scrollbar(top, command=table.yview)
    scroll.pack(side='right', fill='y')
    table.configure(yscrollcommand=scroll.set)
    split.add(top, weight=1)

    bottom = ttk.Frame(split)
    controls = ttk.Frame(bottom)
    controls.pack(side='top', fill='x')
    selector_var = tk.StringVar(value='Common information')
    selector_box = ttk.Combobox(controls, textvariable=selector_var, state='readonly', width=60,
                                values=['Common information'])
    selector_box.pack(side='top', anchor='w', pady=(0, 4))
    actions = ttk.Frame(controls)
    actions.pack(side='top', fill='x', pady=(0, 4))
    copy_syntax = ttk.Button(actions, text='Copy syntax')
    copy_syntax.pack(side='left')
    copy_card = ttk.Button(actions, text='Copy card')
    copy_card.pack(side='left', padx=(5, 0))
    related_frame = ttk.Frame(controls)
    related_frame.pack(fill='x')
    topic_frame = ttk.Frame(controls)
    topic_frame.pack(fill='x')

    detail = tk.Text(bottom, wrap='word', height=12, state='disabled')
    detail.pack(side='left', fill='both', expand=True)
    scroll = ttk.Scrollbar(bottom, command=detail.yview)
    scroll.pack(side='right', fill='y')
    detail.configure(yscrollcommand=scroll.set)
    split.add(bottom, weight=2)

    rows = {}
    selector_rows = {}
    current_text = ''
    current_row = None

    def query_words():
        return search.get().casefold().split()

    def selector_match(row):
        words = query_words()
        if not words:
            return None
        common = _common_card_text(row).casefold()
        for selector in row.get('selectors', []):
            value = _selector_text(selector).casefold()
            if all(word in value or word in common for word in words) and any(word in value for word in words):
                return _selector_label(selector)
        if row.get('selectors') and not all(word in common for word in words):
            return 'All selectors'
        return None

    def displayed_text(row, selected_label):
        text = _common_card_text(row, technical.get())
        if selected_label == 'All selectors':
            text = 'All selectors\n' + _text(row.get('selectors', [])) + '\n\nCommon command information\n' + text
        elif selected_label and selected_label != 'Common information':
            selector = selector_rows.get(selected_label)
            if selector:
                text = ('Selected selector\n' + _selector_text(selector)
                        + '\n\nCommon command information\n' + text)
        if historical.get() and row.get('grammar'):
            text += ('\n\nHistorical registration grammar (initial extraction; it may be superseded). '
                     'Current syntax and unresolved-parts notes are authoritative.\n' + _text(row['grammar']))
        if technical_search.get() and query_words():
            # Expose otherwise invisible matches in catalogue metadata.
            matching_lines = [line.strip() for line in json.dumps(row, ensure_ascii=False, indent=2).splitlines()
                              if any(word in line.casefold() for word in query_words())]
            text += '\n\nTechnical search matches\n' + '\n'.join(matching_lines)
        return text

    def highlight_visible_matches():
        detail.tag_remove('match', '1.0', 'end')
        detail.tag_configure('match', background='#ffe58a', foreground='#202020')
        for word in query_words():
            start = '1.0'
            while True:
                found = detail.search(word, start, stopindex='end', nocase=True)
                if not found:
                    break
                end = f'{found}+{len(word)}c'
                detail.tag_add('match', found, end)
                start = end

    def render(*_, auto_selector=False):
        nonlocal current_text, current_row
        selected = table.selection()
        current_row = rows.get(selected[0]) if selected else None
        selector_rows.clear()
        if current_row:
            labels = ['Common information']
            if current_row.get('selectors'):
                labels.append('All selectors')
            for selector in current_row.get('selectors', []):
                label = _selector_label(selector)
                # Keep duplicate labels addressable while retaining a readable chooser.
                if label in selector_rows:
                    label += f" [{len(selector_rows) + 1}]"
                selector_rows[label] = selector
                labels.append(label)
            selector_box.configure(values=labels)
            match = selector_match(current_row) if auto_selector else None
            chosen = match if match in labels else selector_var.get()
            if chosen not in labels:
                chosen = 'Common information'
            selector_var.set(chosen)
            current_text = displayed_text(current_row, chosen)
        else:
            selector_box.configure(values=['Common information'])
            selector_var.set('Common information')
            current_text = 'No matching commands.'
        detail.configure(state='normal')
        detail.delete('1.0', 'end')
        detail.insert('1.0', current_text)
        highlight_visible_matches()
        detail.configure(state='disabled')
        detail.yview_moveto(0)
        if query_words() and detail.tag_ranges('match'):
            detail.see(detail.tag_ranges('match')[0])
        copy_syntax.configure(state='normal' if current_row else 'disabled')
        copy_card.configure(state='normal' if current_row else 'disabled')
        related_frame.pack_forget()
        for child in related_frame.winfo_children():
            child.destroy()
        if current_row:
            aliases = {alias: row for row in data['commands'] for alias in row.get('aliases', [])}
            linked = []
            for related in current_row.get('related', []):
                target = aliases.get(related)
                if target and target['id'] != current_row['id'] and target not in linked:
                    linked.append(target)
            if linked:
                related_frame.pack(fill='x', pady=2)
                ttk.Label(related_frame, text='Related:').pack(side='left')
                related_box = ttk.Combobox(related_frame, state='readonly', width=75,
                                          values=[target['syntax'] for target in linked])
                related_box.pack(side='left', padx=5)
                related_box.set('Choose a related command')
                related_box.bind('<<ComboboxSelected>>',
                                 lambda event, targets=linked, box=related_box: select_command(targets[box.current()]))
        topic_frame.pack_forget()
        for child in topic_frame.winfo_children():
            child.destroy()
        if current_row and navigate_topic is not None:
            from .scpi_links import topics_for_command, topic_title
            topics = topics_for_command(current_row)
            if topics:
                topic_frame.pack(fill='x', pady=2)
                ttk.Label(topic_frame, text='CAL:').pack(side='left')
                for topic in topics:
                    ttk.Button(topic_frame, text=topic_title(topic),
                               command=lambda topic=topic: navigate_topic(topic)).pack(side='left', padx=2)

    def select_command(row):
        search.set('')
        form.set('All')
        technical_search.set(False)
        refresh()
        table.selection_set(row['id'])
        table.see(row['id'])
        render()

    def refresh(*_):
        previous = table.selection()
        table.delete(*table.get_children())
        rows.clear()
        matching = search_commands(data, search.get(), form.get(), technical_search.get())
        for row in matching:
            rows[row['id']] = row
            table.insert('', 'end', iid=row['id'],
                         values=(row['syntax'], row['form'], row['summary']))
        count.configure(text=f'{len(rows)} / {len(data["commands"])} command forms')
        if rows:
            item = previous[0] if previous and previous[0] in rows else next(iter(rows))
            table.selection_set(item)
        render(auto_selector=True)

    def copy_to_clipboard(value):
        if value:
            frame.clipboard_clear()
            frame.clipboard_append(value)
            frame.update_idletasks()

    def copy_syntax_value():
        if current_row:
            copy_to_clipboard(current_row['syntax'])

    def copy_card_value():
        if current_row:
            copy_to_clipboard(displayed_text(current_row, selector_var.get()))

    copy_syntax.configure(command=copy_syntax_value)
    copy_card.configure(command=copy_card_value)
    selector_box.bind('<<ComboboxSelected>>', render)
    table.bind('<<TreeviewSelect>>', render)
    for variable in (search, form, technical_search):
        variable.trace_add('write', refresh)
    for variable in (technical, historical):
        variable.trace_add('write', render)
    refresh()
    # Expose view state for offline widget checks without a VISA dependency.
    frame.search, frame.form, frame.table, frame.detail = search, form, table, detail
    frame.selector, frame.selector_box = selector_var, selector_box
    frame.technical_search, frame.technical, frame.historical_grammar = technical_search, technical, historical
    frame.copy_syntax, frame.copy_card = copy_syntax, copy_card
    frame.rows = rows
    frame.refresh = refresh
    frame.select_command = select_command
    return frame
