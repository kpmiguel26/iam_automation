# Request Submission Design

Each request is an immutable JSON file named:

`YYYYMMDDTHHMMSSZ_<request_uuid>.json`

Required fields include `request_id`, `created_at_utc`, `created_by`, `computer_name`, `application_version`, `operation_type`, `entity_type`, `entity_id`, `expected_record_version`, `payload`, `reason`, and `status`.

Request folders:

- `requests/pending`
- `requests/imported`
- `requests/approved`
- `requests/rejected`
- `requests/applied`
- `requests/failed`
- `requests/quarantine`

Corrections create a new request. Submitted files are not modified.
