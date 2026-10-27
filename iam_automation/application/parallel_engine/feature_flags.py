"""Operational gates for the in-progress parallel ingestion runtime."""

# Keep file writes disabled until the object model/lifecycle, rule parity,
# finding review, and import-path acceptance checks have passed.
FILE_PROCESSING_ENABLED = False
PROCESSING_PAUSED_MESSAGE = (
    "File processing is paused while object lifecycle, rule parity, finding review, "
    "and import-path acceptance checks are being completed. Discovery remains active."
)
