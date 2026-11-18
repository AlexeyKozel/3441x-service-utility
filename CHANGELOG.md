# 3441x Service Utility 1.0 RC16

RC16 adds offline recovery of NOR dump files and expands the calibration technical reference.

**RC16 has not been tested on a physical instrument. Validation is limited to offline software tests, saved-data checks and static firmware analysis. No physical NOR programming, boot recovery or metrological validation has been performed. The existing live Restore CAL workflow remains experimental.**

## Changes since RC15

- Added **Repair NOR dump…** and the `repair-nor` CLI command with preview and new-file output.
- Transfer intact schema45 CAL from a payload, journal or NOR. Default mode preserves history; optional **Overwrite CAL journal** writes selected CAL to A0 and leaves 31 empty slots, including for full or damaged target journals.
- Restore APP from a complete XS package or donor NOR. Restore Recovery from a complete compatible source, with a separate reset-vector option.
- Check model compatibility against decompressed Recovery content rather than the SA96 personality writer. Unrecognized target content requires an explicit model; firmware sources must be recognized and intact.
- Preserve output byte order and programmer trailers. Reject overwrites and changed sources; verify saved bytes and create a JSON report with source hashes, repair ranges, checksums and remaining limitations.
- Report partial repairs explicitly. Recovery checksum and reset-vector checks are separate.
- Expanded FineMergeGain explanations with configuration fields, finite-width arithmetic and OLD-value timing.
- Added the conditional FPGA MC/MZ/PRE switching profile, separate from unconfirmed saved CAL delay mappings.
- Explained the generated S/Q weighting window and its sampling limits. Existing numerical CAL interpretations and graph models are unchanged.

## Verification

Offline checks cover the existing suite and new repair tests, including CLI and GUI loading. Saved-data scenarios covered donor NOR with original CAL, APP-only repair preserving the original journal, and injected Recovery/header/reset faults. Files were reopened and bytes outside each intended repair region compared. These checks do not establish hardware bootability or calibration accuracy.

## Scope and limitations

Only new local files are written by NOR repair; no instrument connection is made. Unknown firmware content is not automatically classified as damaged. Model matching does not certify every hardware configuration. Full donor recovery retains donor state outside the selected replacement regions; NOR does not contain a serial number for specimen matching.

CAL transfer initially supports schema45 with recognized 34410A/34411A APP 2.43. Full/damaged journals are overwritten only when explicitly requested. Partial XS packages are not accepted as complete firmware recovery sources. Reset-vector restoration needs a source containing a valid matching vector.

Existing live APP upload, identity switching and Restore CAL retain their previous workflow checks. No calibration engine, calibrator automation, VxWorks console or new live recovery upload is added.

See [NOR repair guide](docs/NOR-REPAIR.md) and [safety notes](SAFETY.md).

---

# 3441x Service Utility 1.0 RC15

RC15 expands calibration analysis, backup comparison and the built-in technical reference.

**This release has not been tested on a physical instrument. Validation is limited to offline software tests, saved-data regression checks and static firmware analysis. In particular, CAL restore is experimental and has not been validated on hardware.**

## Changes since RC14

- Expanded calibration-table handling and coefficient interpretation, including calculation and application paths, formulas, applicability and linked reference topics.
- Added an offline hidden SCPI reference covering 108 command forms for APP11 2.43, with arguments, responses, firmware paths, concrete side effects and evidence limitations. Browsing the reference does not execute commands.
- Added quadratic-correction and filter impulse-response plots, filter overlays for slot comparisons, and Scale/Divider trends between slots.
- Added comparison of multiple current-CAL backup files. The earliest dated file is the default reference; dated trends keep different instrument serial numbers separate. Missing JSON or operating-time metadata does not prevent comparison.
- Added CSV export of the filtered A/B comparison, including stored values, interpreted changes, file names, serial numbers, dates and hashes.
- Added serial-number and UTC timestamp names for current-CAL backups, plus optional accumulated operating hours in JSON metadata. Failure to read the optional counter does not discard the CAL backup.
- Added backup and inspection of the complete 32-slot CAL journal (256 KiB), without requiring a full NOR backup.
- Added experimental Restore CAL for 34411A APP 2.43/schema45: file and serial checks, a mandatory pre-write backup, working-memory read-back, a separate confirmation for CAL:STORE, and verification of the current NOR slot. Journal-slot restore is not provided.
- Added backup-format help and a shared CAL interpretation/comparison engine.

## Boundaries

Filter plots are conditional software projections, not a measured complete instrument frequency response. The quadratic plot shows one added correction, not residual INL. Backup dates are not calibration dates; coefficient changes alone do not establish instrument drift or calibration quality.

Restore uses two sequential confirmations in one workflow: load working CAL, then optionally persist it in NOR. Declining persistence leaves the loaded working values in place. An interrupted write can leave an uncertain state; there is no automatic retry or rollback. Static analysis does not establish immediate activation of every coefficient in every measurement mode.

No new calibration procedure, calibrator automation or VxWorks console is included.


---

# Changelog

## v1.0.0-rc14

Expanded calibration-table handling and coefficient interpretation.

- Added a searchable CAL viewer with interpreted values, formulas and conditional physical-unit conversions.
- Added current/historical CAL-slot comparison with changed-value highlighting.
- Added filter curves and collapsible coefficient vectors.
- Expanded ADC, AC/SLOW and delay explanations, including the APP 2.43 MC/MZ reference.
- Preserved raw CAL values and existing write-workflow gates.
- Validation: offline regression tests; no new hardware validation is claimed.

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
