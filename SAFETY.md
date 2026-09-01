# Safety notes

This utility exposes service operations that can alter persistent memory and executable firmware. Use it only on an instrument you are prepared to recover.

## Before writing

- Confirm the VISA resource and the instrument identity shown by the utility.
- Use stable mains power and a reliable interface connection.
- Preserve every automatically created backup outside the working computer.
- Keep the original vendor updater package available, but do not modify it.
- Do not upload an APP image whose provenance or integrity is unknown.

## Identity switching

The utility limits boot-identity targets to 34410A and 34411A. It creates an original SA96 backup even when the optional full service backup is not selected. Reboot is permitted only after the complete programmed SA96 sector matches the planned bytes.

Changing an identity does not add hardware capabilities. The operator remains responsible for confirming that the physical instrument is compatible with the selected identity.

## APP upload

The live APP path accepts only validated 34410A or 34411A factory `instrumentimage` packages. It does not expose arbitrary firmware writes or general recovery `updateimage` upload.

When the upload protocol reports completion, follow the prompt and manually power-cycle the instrument. Do not interrupt power while blocks are being transferred. The utility does not automatically repeat a block or the package after a timeout because the instrument's internal state may already have changed.

## Backups and calibration

Backups may contain instrument-specific serial, configuration, or calibration-related data. Treat them as sensitive device records and do not publish them. Never restore data from a different physical instrument unless you fully understand the consequences.

The software is provided without warranty. Use it entirely at your own risk. The author accepts no responsibility for bricked or otherwise damaged equipment, lost calibration, lost data, or unsafe behavior.
