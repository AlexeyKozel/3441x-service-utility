# Offline NOR repair

Open **Offline analysis > Repair NOR dump…**. This workflow edits a copy of a
saved NOR file. It does not connect to or program an instrument.

## Sources and compatibility

Select a complete target NOR and one or more sources:

| Operation | Source |
|---|---|
| CAL | Valid schema45 payload, CPU-order 256 KiB journal, or full NOR with a unique intact current/fallback record |
| APP | Full donor NOR or complete XS instrumentimage |
| Recovery | Full donor NOR, complete XS updateimage, or CPU-order logical Recovery image |
| Reset vector | A Recovery source that also contains a valid reset vector |

Model identity comes from recognized decompressed Recovery content, not the
SA96 personality writer. If target Recovery content cannot be identified,
select the intended model explicitly. Recognized contradictory models are
rejected. Donor firmware must have a valid checksum and recognized compatible
content; a partial SA96 update package is not a complete Recovery source.
An unknown hash is not itself evidence of corruption.

CAL transfer currently requires a recognized, intact 34410A/34411A APP 2.43 in
the resulting image. NOR has no instrument serial number; file names and external
metadata do not establish that a CAL backup belongs to the target specimen.

## Preserve history or overwrite the journal

The default mode adds CAL to a free slot and retires old active markers while
preserving historical bodies. It rejects full, damaged or ambiguous target journals.

Select **Overwrite CAL journal with selected calibrations (output file only)**
to replace the entire 256 KiB journal, including a damaged/full journal. Selected
valid CAL becomes the only active record in A0; the other 31 slots are empty.
All previous journal entries are removed from the output copy. Original files
remain unchanged. This does not bypass validation of the selected CAL source.

A typical donor-based recovery uses a compatible intact donor NOR and the
original instrument's surviving CAL backup with Overwrite enabled. Other NOR
state remains donor data. This is not a guarantee of complete individual-state
restoration or measurement accuracy. Instrument calibration counters outside
this record are not updated by offline CAL transfer.

## Preview and save

Use **Preview in main log**, then **Save repaired dump…**. The save action builds
a fresh plan and displays it before confirmation. Output BIN and companion
`.bin.json` must be new files; existing files are never overwritten. The report
records source hashes, identity basis, affected ranges, CAL mode, checksums,
reset status and remaining limitations. Saved bytes are read back and verified.

Byte order is detected when possible; explicitly select CPU or programmer
(pair-swapped) order when damaged headers make detection ambiguous. Original
byte order and any bytes after the 8 MiB NOR are preserved. Check the output
size expected by your programmer: preserved trailing bytes are not flash capacity.

APP repair replaces the source's logical image, not the entire six-megabyte
address window containing CAL. Complete XS sources may omit reserved header
bytes +8..+15; those bytes remain from the target and are reported as uncovered.
Source logical length defines the replacement extent, which may differ from
the original APP length. Consult the reported offsets before saving.

Reset-vector restoration is a separate checkbox. A valid Recovery checksum
does not validate the last NOR word. Without the checkbox a damaged reset vector
remains unchanged and is reported. Partial repair of one region may leave other
regions damaged; the result is then explicitly marked as partial.

## CLI examples

Preview without writing files:

```powershell
run_cli.bat repair-nor target.bin --app donor.bin
```

Restore only APP and preserve the target's other regions:

```powershell
run_cli.bat repair-nor target.bin --app donor.bin --output repaired.bin
```

Replace donor calibration history with the original instrument's saved CAL:

```powershell
run_cli.bat repair-nor donor.bin --cal original_cal.bin --overwrite-cal-journal --output restored.bin
```

Repair Recovery and reset when target Recovery content is unrecognizable:

```powershell
run_cli.bat repair-nor target.bin --recovery donor.bin --model 34410A --restore-reset --output repaired.bin
```

Use `--order` for the target and `--donor-order` for full donor NOR files.
Standalone logical Recovery images and journal files are CPU order.

## Validation boundary

RC16 was tested with offline tests, saved NOR data and injected faults, including
separate Recovery/reset faults. Physical programming, booting and metrological
performance have not been tested. No donor images or calibration files are
distributed with the utility.
