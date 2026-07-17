# Testing

The POC must run on Python 3.10+.

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Required failure tests:

- Two users submit requests simultaneously.
- Duplicate `RequestID`.
- Malformed JSON.
- Unsupported application version.
- Unauthorized requester.
- Unauthorized writer.
- Requester attempts to approve own request.
- Access file unavailable or already open.
- Backup failure.
- Mid-batch write failure.
- Audit append failure.
- Published version changes before publish.
- Checksum mismatch.
- OneDrive conflict copy.
- Process stops before archive.
- Process stops after local database update.
- Process stops after publication before status update.
- Excel validation failure.

Each test must document expected behavior, recovery, user-facing message, audit event, and retry safety.
