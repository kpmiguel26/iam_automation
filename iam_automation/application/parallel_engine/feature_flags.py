"""Operational gates for the in-progress parallel ingestion runtime."""

# Keep file writes disabled until the physical object model, template lifecycle
# handling, and Rules Engine integration have passed their acceptance checks.
FILE_PROCESSING_ENABLED = False
PROCESSING_PAUSED_MESSAGE = (
    "File processing is paused while the physical object model, template lifecycle, "
    "and import rules integration are being completed. Discovery remains active."
)
