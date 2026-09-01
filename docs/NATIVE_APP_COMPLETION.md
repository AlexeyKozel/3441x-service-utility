# Native APP completion behavior

The original 3441x updater has distinct completion paths for `instrumentimage` and `updateimage` packages.

For an APP `instrumentimage`, the native path displays a power-cycle request after the image has been transferred. It does not issue `:diag:reboot`. The explicit reboot command belongs to the separate `updateimage` path.

RC11 preserves that distinction:

1. Validate the `.xs` structure, image type, model, and checksums.
2. Transfer every block exactly once.
3. Validate the updater's reported checksum and END status.
4. Ask the operator to power-cycle the instrument manually.
5. Reconnect read-only and verify the final `*IDN?` model.

The utility never treats a transport timeout as permission to retry a block or the complete package.
