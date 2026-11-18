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
