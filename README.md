# 3441x Service Utility 1.0 RC15

An unofficial service utility for Agilent/Keysight 34410A and 34411A digital multimeters, with a Windows GUI and command-line interface.

**RC15 has not been tested on a physical instrument. Checks are offline only. CAL restore is experimental and has not been validated on hardware.** See [release notes](RELEASE_NOTES.md) and [SAFETY.md](SAFETY.md).

## Start

Use Python 3.11 or later with Tkinter. Offline analysis uses the standard library. Instrument communication additionally requires a compatible VISA backend and PyVISA:

```powershell
py -m pip install -r requirements-live.txt
run_gui.bat
run_cli.bat --help
py -B verify_release.py
```

Supply the VISA resource appropriate to your installation. No firmware, vendor binaries, instrument dumps or user calibration backups are included.

## Calibration analysis

Inspect CAL shows decoded coefficients, physical equivalents where established, calculation/application descriptions and a linked technical reference. It also provides filter and quadratic-correction plots. Plot conditions are shown in the interface; these are not measurements of complete instrument performance.

CAL history opens either a full NOR dump or a standalone 256 KiB CAL journal. It identifies current and historical slots and compares their stored bytes and interpreted values. Slot order is not a dated service history.

Compare CAL backups accepts multiple current-CAL files. It selects the earliest dated snapshot as reference and allows manual A/B selection. Dates come from matching JSON metadata or recognized file names, never filesystem modification times. Missing metadata does not prevent comparison. Unknown dates can be supplied for the current session. Time trends use dated snapshots with the same known serial number; backup dates are not calibration dates.

Export visible rows to CSV saves the filtered A/B table, expanding matching filter groups. CSV uses UTF-8 with BOM and comma separators. Import exact stored values as text in spreadsheet software when preserving all digits matters.

## Backup and restore

- Save CAL writes `SERIAL_CAL_<UTC timestamp>.bin` and `.bin.json`. The schema45 payload is 4,934 bytes, including its 10-byte header. Optional operating hours and identity metadata are stored in JSON; failure to read the counter does not prevent backup.
- Save CAL history reads all 32 journal slots (256 KiB) into `SERIAL_CAL_HISTORY_<UTC timestamp>.bin`, with JSON metadata. Do not operate the instrument during this sequential read.
- A full NOR backup contains substantially more than CAL. Backup file formats in the GUI explains which viewer accepts each format.
- Experimental Restore CAL accepts current schema45 CAL payloads for 34411A APP 2.43. It checks the file and instrument, requests confirmation for a missing/different filename serial, and saves a pre-write backup. Loading working CAL and saving to NOR require separate confirmations. Working CAL is read back byte for byte; persistence checks the current NOR slot. Declining NOR storage leaves loaded working values in place. Errors do not trigger automatic retries or rollback. Journal and full NOR files cannot be restored through this workflow.

## Technical reference and other workflows

Hidden SCPI reference documents 108 forms from static APP11 2.43 analysis, including arguments, selectors, responses, effects and unresolved details. Browsing it does not send commands. The CLI provides `scpi-reference --format text`.

Existing workflows include diagnostic reads, service backups, offline NOR/XS inspection and simulation, bounded boot-identity switching and original APP image upload. These can modify persistent storage: read [SAFETY.md](SAFETY.md). General updateimage upload remains blocked. APP upload requires a manual power cycle when prompted and does not automatically retry failed blocks.

The [conversion walkthrough](docs/CONVERSION-WALKTHROUGH.md) records earlier hardware work; it is not hardware validation of RC15.

## Verification

```powershell
py -B -X utf8 -m unittest discover -s tests -v
```

Private evidence tests are excluded from this public package; synthetic tests use placeholder serial numbers. Tests do not require a connected instrument. Manifest verification checks package integrity, not hardware safety or metrological correctness.

Source code is covered by the [MIT License](LICENSE). This project is not affiliated with or endorsed by Keysight, Agilent or Hewlett-Packard.
