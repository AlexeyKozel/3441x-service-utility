"""English help for backup formats; no instrument access."""
import tkinter as tk
from tkinter import ttk

TEXT = '''CURRENT CAL — Save CAL…
One logical calibration set: schema45, 4934 bytes (10-byte header + 4924-byte body).
Open: Offline analysis → Inspect CAL payload…
Compare files: CAL history → Compare CAL backups…
Restore: Backup / Restore → Restore CAL… (currently 34411A APP 2.43 only).
This file contains the exported working CAL, not all historical NOR slots.

CAL JOURNAL — Save CAL history…
All 32 physical CAL slots, 256 KiB, in CPU byte order. Includes current, retained, empty and potentially damaged slots.
Open: CAL history → Open NOR / CAL journal…
The utility does not restore this journal or selected slots from it.

FULL NOR — Read complete NOR…
The full 8 MiB flash image, including firmware and the CAL journal.
Open: Offline analysis → Inspect NOR dump…
Analyze CAL slots: CAL history → Open NOR / CAL journal…
Restore CAL does not accept a full NOR image. Arbitrary whole-NOR restoration is not provided.

JSON METADATA
Save CAL and Save CAL history also create a neighboring .bin.json file with identity, UTC save time, hashes and optional operating-time data.
Keep it beside the binary file. JSON is not a replacement for the binary backup.
Missing JSON or operating time does not prevent coefficient comparison. Recognized filenames provide fallback serial/date information; unknown dates stay unknown.

FILE NAMES
SERIAL_CAL_<UTC-date-time>.bin: current logical CAL.
SERIAL_CAL_HISTORY_<UTC-date-time>.bin: all journal slots.
File contents and size determine the accepted format; renaming does not convert a file.
Backup dates are not necessarily calibration dates. Physical slot order is not a dated history.
'''


def show_file_formats(parent):
    window = tk.Toplevel(parent)
    window.title('Backup file formats')
    window.geometry('860x660')
    frame = ttk.Frame(window, padding=12)
    frame.pack(fill='both', expand=True)
    text = tk.Text(frame, wrap='word', padx=10, pady=10)
    scroll = ttk.Scrollbar(frame, command=text.yview)
    scroll.pack(side='right', fill='y')
    text.pack(fill='both', expand=True)
    text.configure(yscrollcommand=scroll.set)
    text.insert('1.0', TEXT)
    text.configure(state='disabled')
    ttk.Button(window, text='Close', command=window.destroy).pack(pady=(0,10))
    return window
