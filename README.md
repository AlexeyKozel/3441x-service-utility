# 3441x Service Utility

An unofficial service and recovery utility for Agilent/Keysight 34410A and 34411A digital multimeters.

The current public release is **v1.0.0-rc12**. It provides a Windows GUI and a console interface for diagnostic reads, backups, offline package inspection, boot-identity maintenance, and controlled upload of original APP images.

> [!WARNING]
> This software can write persistent instrument storage and firmware. A failed operation or power loss can brick the instrument. Use it entirely at your own risk. The author accepts no responsibility for damaged equipment, data loss, or calibration issues. Read [SAFETY.md](SAFETY.md) before enabling any write operation.

## Features

- Reads instrument identity and diagnostic information through VISA.
- Creates service-memory and native 64 KiB SA96 backups.
- Inspects NOR dumps, CAL payloads, and factory `.xs` packages offline.
- Simulates an `.xs` package against a copy of a NOR image.
- Switches the boot identity between 34410A and 34411A with exact read-back verification.
- Uploads original 34410A or 34411A APP `instrumentimage` packages.
- Uses progress reporting for long reads and writes.
- Stores backups in `3441x Service Utility Backups` beside the launched utility.

The repository contains no firmware, updater packages, instrument dumps, calibration data, or vendor binaries.

## Requirements

- Windows 10 or later
- Python 3.10 or later
- A VISA implementation compatible with your interface
- PyVISA

Install the Python dependency:

```powershell
py -m pip install -r requirements-live.txt
```

## Running the utility

GUI:

```powershell
run_gui.bat
```

Console help:

```powershell
run_cli.bat --help
```

Pass the VISA resource accepted by your VISA installation, for example `GPIB0::20::INSTR`.

## Write-operation behavior

Identity switching first saves the original SA96 sector, uploads a hash-bound patched package, and performs a complete read-back. The utility handles either an automatic reboot or an explicit reboot only after the programmed sector has been verified.

APP upload accepts only factory-format `instrumentimage` packages identified as 34410A or 34411A. Cross-loading between those two models is allowed after a simple Yes/No confirmation. General `updateimage` upload remains blocked.

After a native APP package is accepted, the instrument may remain at `UPDATING FIRMWARE`. This matches the original updater path: the utility asks for a manual power cycle and then waits for the instrument to reconnect. It deliberately does not send `:diag:reboot` for APP `instrumentimage` completion.

No firmware block or package is automatically retried after a timeout.

## Tests

```powershell
py -X utf8 -m unittest discover -s tests -v
```

Some evidence-bound tests are skipped when the private research artifacts are not present. The public tests and runtime do not require those artifacts.

## Building a release archive

```powershell
py -X utf8 build_release.py
```

The command creates a versioned ZIP and `SHA256SUMS.txt` under `dist/v1.0.0-rc12`.

## Project status

RC12 is a hardware-validation release. A successful APP upload and manual power-cycle boot have been observed on real hardware, but this is not a warranty of safety or compatibility with every instrument state.

This project is not affiliated with or endorsed by Keysight Technologies, Agilent Technologies, or Hewlett-Packard.

## License

The source code is available under the [MIT License](LICENSE). Vendor firmware, updater packages, instrument dumps, and calibration data are not included and are not licensed by this project.
