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
