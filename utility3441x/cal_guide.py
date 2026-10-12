"""Shared, offline CAL reference pages and links to loaded coefficients."""
from tkinter import ttk
import tkinter as tk

PAGES = {
    'dcv': ('DC voltage scale and nonlinearity',
            'The linear stage uses the selected range gain and the Front or Rear offset.\n\n'
            'With accumulated input S and total packet weight T:\n'
            '  g = G/T; o = round_away(O*T)\n'
            '  V0 = double_signed(wrap64(S-o))*g\n\n'
            'On the checked 10 V path, the enabled quadratic stage adds:\n'
            '  V = V0 + AdcQuad*V0*V0\n\n'
            'Gain calibration depends on the range. The 100 mV procedure averages the '
            'positive and negative gain candidates. The positive 10 V point uses the previous '
            'AdcQuad; the negative point calculates a new AdcQuad. Other checked ranges write '
            'an accepted reference/normalized-sample candidate.\n\n'
            'Offset calibration stores the zero-condition sample divided by total weight. '
            'The coefficient cards explain the individual calculations and their limits.\n\n'
            'These are APP11 2.43 software paths. The stored values do not establish '
            'the accuracy of the instrument or the quality of the calibration reference.'),
    'adc': ('ADC profiles and feedback',
            'DCV, ACV and ACI have separate ADC coefficient sets. Use values from one '
            'profile together; the profile label does not identify the currently active instrument mode.\n\n'
            'DcOffset (D) and PiOffset (P) form an alternating 64-entry table: D+P, D-P. '
            'LutGain forms the coarse feedback table. Jitter controls a separate digital '
            'sequence contributing to feedback.\n\n'
            'FineMergeGain aligns the fine difference with the retained feedback history. '
            'In the ordinary algebraic form:\n'
            '  M = 65536*C_history + G*(fine_previous-fine_current)\n'
            '  G = low10(round_away(FineMergeGain*65536))\n'
            'Finite-width encoding and pipeline alignment still apply. This is not a '
            'multiplier on the complete voltage, current or resistance reading.\n\n'
            'N_Decisions, Nf_Slope and FineSamplOffset position the digital cycle and sampling '
            'requests. Their cards contain the bounded formulas and conditional timing projections.\n\n'
            'The links below preserve the selected ADC profile. Each card distinguishes '
            'a saved coefficient from the register values calculated from it.'),
    'dci': ('DC current scale and offset',
            'The selected range gain converts the accumulated input into amperes. The offset '
            'is selected for the Front or Rear terminals. With accumulation S and total weight T, '
            'the ordinary linear stage is:\n'
            '  I = double_signed(wrap64(S-round_away(O*T)))*(G/T)\n\n'
            'Gain calibration contains G_new=G_old*reference/sample. The complete upstream '
            'processing of this captured sample is not yet established. Offset calibration '
            'stores the captured zero-condition record divided by total weight.\n\n'
            'The displayed gain ratio compares with the firmware reference. It is not a '
            'measured accuracy error. The displayed offset contribution precedes rounding '
            'and any later corrections.'),
    'res': ('Resistance scale, offset and divider',
            'Resistance uses separate 2-wire and 4-wire gain and offset banks. Range, '
            'offset-compensation mode and Front/Rear selection determine the applicable fields.\n\n'
            'The linear stage subtracts round_away(O*T) from the accumulated input and '
            'multiplies by G/T. Absolute-value handling follows. On the checked ordinary '
            '100 Mohm and 1 Gohm paths, the divider correction is:\n'
            '  R = x*D/(D-x), D = Divider10M\n'
            'The consumer requires x < 0.9999*D and has additional overload guards.\n\n'
            'The 10 Mohm gain-calibration branch also obtains a separate sample under a '
            'special front-end configuration. A sample accepted between 8 and 12 Mohm is '
            'stored directly as Divider10M. These are firmware acceptance bounds.\n\n'
            'CurrentSrcDelay participates in settling after current-source changes. Its '
            'nominal time projection and the separate MC/MZ delay evidence are explained '
            'on the timing page and individual cards.'),
    'ac': ('AC scale, noise and filters',
           'ACV and ACI select range-specific amplitude gains and squared-noise terms. '
           'A useful ordinary MED/FAST pre-rolldown form is:\n'
           '  y = G*sqrt(P-N)\n'
           'Here P is the internal second-moment quantity and N the selected squared-noise '
           'term. Additional mode-dependent processing and guards still apply.\n\n'
           'G^2*N expresses the noise term in output units squared. For N >= 0, '
           '|G|*sqrt(N) is its equivalent RMS scale; it is not a constant subtracted '
           'from the displayed reading or a measurement of instrument noise.\n\n'
           'MED and SLOW IIR coefficients control filtering and compensation. SLOW noise '
           'scaling includes 1+AcvSlowNoiseGainSquared. The runtime link from the saved '
           'AcvSlowDcGainSquared field remains unresolved.\n\n'
           'Flatness and low-pass arrays describe complete filters. Individual taps do '
           'not have independent frequency labels. Use Filter curves for their response '
           'and retain the displayed clock/profile conditions; this is not the complete '
           'instrument frequency response.'),
    'freq_cap': ('Frequency, period and capacitance',
                 'FreqGain scales the software counter base:\n'
                 '  Fbase = 106250000*FreqGain\n'
                 '  dt = (B-A)/Fbase; frequency = N/dt; period = dt/N\n'
                 'These expressions assume valid records and nonzero divisors. Increasing '
                 'FreqGain increases frequency and decreases period for fixed counters.\n\n'
                 'Frequency gain calibration computes G_new=G_old*reference/sample. '
                 'The individual card states the verified producer boundaries.\n\n'
                 'The capacitance calculation also consumes FreqGain. It subtracts the '
                 'selected Front or Rear CapOffset from the calculated capacitance. '
                 'CapOffset is stored in farads; its signed contribution is -CapOffset. '
                 'It is not the capacitance of the currently connected component.'),
    'timing': ('Settling and autozero timing',
               'CurrentSrcDelay participates in current-source settling. The checked '
               'software projection is 19.952941176 microseconds per unit; 75 corresponds '
               'to approximately 1.50 ms. Other waits can increase the actual delay.\n\n'
               'MC denotes the signal-measurement phase and MZ the zero-measurement phase '
               'of the autozero cycle. The saved McDelay and MzDelay fields have not been '
               'connected conclusively to the working delay counters. Their displayed '
               'time estimates are hypotheses, not confirmed active delays.\n\n'
               'Open either MC/MZ card and its Delay reference for the APP 2.43 tables '
               'by function, range and NPLC. Those tables describe separate firmware '
               'paths and do not establish that these saved fields are unused.'),
    'drive': ('Heater and precharge control',
              'HeaterGain and HeaterRes participate in heater drive, rather than the '
              'linear measurement gain. For positive target power, before rounding and limits:\n'
              '  drive = 77.272727...*sqrt(HeaterRes*Ptarget)/HeaterGain\n\n'
              'At fixed HeaterRes and Ptarget, the ratio to the initial HeaterGain=1.33 '
              'is 1.33/HeaterGain. The voltage-dependent target-power branch is selected '
              'for DCV; the checked threshold uses the scaled voltage magnitude, not '
              'the range name alone.\n\n'
              'PrechargePwm controls digital PWM. Its displayed duty applies to the '
              'specified enabled PWM profile. Read the individual card for encoding '
              'and operating conditions.'),
    'storage': ('Working CAL and saved CAL',
                'A CAL export serializes the current registered calibration values in memory. '
                'A NOR dump contains saved CAL records. These are different sources and can differ.\n\n'
                'A calibration routine can change a working scalar. The separate CAL:STORE path '
                'saves the CAL group to NOR. Updating a scalar alone does not prove a successful commit.\n\n'
                'The CAL history view compares records present in a NOR dump. A standalone CAL '
                'payload does not establish which NOR slot held it or whether the same values '
                'are still active on an instrument.\n\n'
                'This viewer is read-only. The formulas explain use; they do not certify that '
                'a saved coefficient is correct for a particular instrument.')
}

TOPIC_FAMILIES = {
    'dcv': {'AdcQuad', 'DcvGain', 'DcvOff'},
    'dci': {'DciGain', 'DciOff'},
    'res': {'ResGain', 'ResOff', 'Res4Gain', 'Res4Off', 'Divider10M'},
    'ac': {'AcvGain', 'AciGain', 'AcvSqNoise', 'AciSqNoise', 'flatness', 'lp',
           'AcvMedIirDenomCoef', 'AcvMedIirNumeratorCoef', 'AcvSlowIirDenomCoef',
           'AcvSlowIirNumeratorCoef', 'AcvSlowDcGainSquared', 'AcvSlowNoiseGainSquared'},
    'freq_cap': {'FreqGain', 'CapOffset'},
    'timing': {'CurrentSrcDelay', 'McDelay', 'MzDelay'},
    'drive': {'HeaterGain', 'HeaterRes', 'PrechargePwm'},
}


def topic_for(row):
    family = row.get('meaning', {}).get('family', '')
    if family.startswith('Adc_'):
        return 'adc'
    for topic, families in TOPIC_FAMILIES.items():
        if family in families:
            return topic
    return 'storage'


def linked_indices(rows, topic, origin=None):
    profile = None
    if origin is not None and topic_for(origin) == 'adc':
        profile = origin.get('meaning', {}).get('groupId')
    return [i for i, row in enumerate(rows)
            if topic_for(row) == topic and topic != 'storage'
            and (topic != 'adc' or profile is None
                 or row.get('meaning', {}).get('groupId') == profile)]


class CalGuide(ttk.Frame):
    def __init__(self, parent, rows, display_rows, navigate):
        super().__init__(parent, padding=8)
        self.rows, self.display_rows, self.navigate = rows, display_rows, navigate
        self.origin = None
        self.topic = 'dcv'
        bar = ttk.Frame(self)
        bar.pack(fill='x')
        self.page = tk.StringVar(value=PAGES['dcv'][0])
        select = ttk.Combobox(bar, state='readonly', textvariable=self.page,
                             values=[p[0] for p in PAGES.values()], width=38)
        select.pack(side='left')
        select.bind('<<ComboboxSelected>>', self._choose)
        ttk.Button(bar, text='Working / saved CAL', command=lambda: self.show('storage', self.origin)).pack(side='left', padx=8)
        self.commands_button = ttk.Button(bar, text='Related hidden SCPI commands',
                                         command=self._open_commands)
        self.commands_button.pack(side='left', padx=4)
        self.context = ttk.Label(self)
        self.context.pack(anchor='w', pady=6)
        split = ttk.Panedwindow(self, orient='vertical')
        split.pack(fill='both', expand=True)
        text_frame = ttk.Frame(split)
        self.text = tk.Text(text_frame, wrap='word', height=16, state='disabled')
        self.text.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(text_frame, command=self.text.yview)
        scroll.pack(side='right', fill='y')
        self.text.configure(yscrollcommand=scroll.set)
        split.add(text_frame, weight=2)
        links = ttk.Frame(split)
        self.links_title = ttk.Label(links, text='Related coefficients in this file — select one and open its card')
        self.links_title.pack(anchor='w', pady=4)
        table_frame = ttk.Frame(links)
        table_frame.pack(fill='both', expand=True)
        self.table = ttk.Treeview(table_frame, columns=('parameter', 'value'), show='headings', selectmode='browse', height=7)
        self.table.heading('parameter', text='Calibration parameter')
        self.table.heading('value', text='Value in this file')
        self.table.column('parameter', width=460)
        self.table.column('value', width=270)
        self.table.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(table_frame, command=self.table.yview)
        scroll.pack(side='right', fill='y')
        self.table.configure(yscrollcommand=scroll.set)
        self.open_button = ttk.Button(links, text='Open selected coefficient', command=self.open_selected)
        self.open_button.pack(anchor='w', pady=5)
        self.table.bind('<<TreeviewSelect>>', self._selection)
        self.table.bind('<Double-1>', lambda event: self.open_selected())
        self.table.bind('<Return>', lambda event: self.open_selected())
        split.add(links, weight=1)
        self.show('dcv')

    def _choose(self, *_):
        self.show(next(k for k, v in PAGES.items() if v[0] == self.page.get()), self.origin)

    def _open_commands(self):
        from .scpi_links import open_commands
        open_commands(self, self.topic)

    def show(self, topic, origin=None):
        self.topic, self.origin = topic, origin
        self.commands_button.configure(state='normal' if topic == 'storage' else 'disabled')
        self.page.set(PAGES[topic][0])
        profile = (origin or {}).get('meaning', {}).get('groupId')
        same_profile = topic == 'adc' and origin is not None and topic_for(origin) == 'adc'
        self.context.configure(text=('ADC profile: ' + {0: 'DCV', 1: 'ACV', 2: 'ACI'}.get(profile, str(profile))
                                     if same_profile else 'Reference: 34411A APP 2.43'))
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', PAGES[topic][0] + '\n\n' + PAGES[topic][1])
        self.text.configure(state='disabled')
        self.text.yview_moveto(0)
        self.table.delete(*self.table.get_children())
        indices = linked_indices(self.rows, topic, origin)
        vectors = {}
        for i in indices:
            meaning = self.rows[i].get('meaning', {})
            if meaning.get('family') in ('flatness', 'lp') and meaning.get('nameBase'):
                key = (meaning['family'], meaning['nameBase'])
                vectors.setdefault(key, []).append(i)
        for i in indices:
            display = self.display_rows[i]
            meaning = self.rows[i].get('meaning', {})
            group = vectors.get((meaning.get('family'), meaning.get('nameBase')))
            if group:
                if i != group[0]:
                    continue
                title = display['title'].rsplit(', tap ', 1)[0].replace(' filter tap —', ' filter —')
                value = f'{len(group)} coefficients — opens first coefficient'
            else:
                title, value = display['title'], display['value']
            self.table.insert('', 'end', iid=str(i), values=(title, value))
        self.links_title.configure(text=('Open a CAL file to browse its coefficients.' if not self.rows else
                                        'No coefficient links on this general page.' if topic == 'storage' else
                                         'Related coefficients in this file — select one and open its card'))
        self._selection()

    def _selection(self, *_):
        self.open_button.configure(state='normal' if self.table.selection() else 'disabled')

    def open_selected(self):
        selected = self.table.selection()
        if selected:
            self.navigate(int(selected[0]))
