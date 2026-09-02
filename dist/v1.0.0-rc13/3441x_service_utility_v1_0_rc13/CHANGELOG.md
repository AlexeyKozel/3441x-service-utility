# Changelog

## v1.0.0-rc13

- Matched the OEM APP block handshake with one bounded 100-byte VISA read per acknowledgement.
- Restored the OEM 5-second timeout for the main firmware block loop.
- Removed the premature reconnect attempt after a successful APP `END`; the manual power-cycle prompt is now shown immediately.
- Preserved fail-closed behavior: timeout, short write, and ambiguous results never trigger an automatic block retry.
- Fixed post-identity-switch verification when the old APP still reports the source model before the matching target APP is installed.
- Added regression coverage for bounded reads, short writes, timeout behavior, automatic reboot races, and APP completion ordering.
- Hardware-tested sequential uploads of original 34410A and 34411A APP packages.

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
