# Changelog

## v1.0.0-rc11

- Added original 34410A/34411A APP `instrumentimage` upload.
- Allowed deliberate APP cross-loading between 34410A and 34411A after a Yes/No confirmation.
- Matched native APP completion behavior: request a manual power cycle, do not send `:diag:reboot`, and wait for read-only reconnect verification.
- Added automatic recovery from identity-write reboot during full SA96 read-back.
- Moved automatic backups beside the launched utility.
- Removed typed confirmation phrases from GUI write operations.
- Retained strict package validation and no-retry timeout behavior.
