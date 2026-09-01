# Changelog

## v1.0.0-rc12

- Added a prominent diagnostics warning when a 34411A reports the uniquely identified 34410A Recovery revision 2.40.
- Added a separate warning for an incomplete conversion when APP identity and SA96 boot personality do not match.
- Kept Recovery-model inference fail-closed: ambiguous revision 2.35 is reported but is not treated as proof of conversion.

## v1.0.0-rc11

- Added original 34410A/34411A APP `instrumentimage` upload.
- Allowed deliberate APP cross-loading between 34410A and 34411A after a Yes/No confirmation.
- Matched native APP completion behavior: request a manual power cycle, do not send `:diag:reboot`, and wait for read-only reconnect verification.
- Added automatic recovery from identity-write reboot during full SA96 read-back.
- Moved automatic backups beside the launched utility.
- Removed typed confirmation phrases from GUI write operations.
- Retained strict package validation and no-retry timeout behavior.
