"""Operational gates for the parallel ingestion runtime."""

# File processing is enabled for this app by explicit user direction. The route
# still requires an approver role and a valid CSRF token for every file.
FILE_PROCESSING_ENABLED = True


PROCESSING_PAUSED_MESSAGE = (
    "File processing is paused. Discovery remains active."
)
