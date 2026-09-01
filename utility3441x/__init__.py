"""Safety-focused service utility for HP/Agilent 34410A, 34411A and L4411A."""

__version__ = "1.0.0-rc11"

# RC11 permits only 34410A/34411A APP (instrumentimage) packages through the
# broad updater UI. Recovery/updateimage upload stays disabled. Identity
# switching remains separately bounded to a fresh session SA96.
LIVE_FIRMWARE_WRITE_ENABLED = False
LIVE_APP_IMAGE_WRITE_ENABLED = True
LIVE_IDENTITY_WRITE_ENABLED = True

# Backward-compatible name means the broad firmware-write surface, not the
# separately bounded identity workflow.
LIVE_WRITE_ENABLED = LIVE_FIRMWARE_WRITE_ENABLED
