# Publication Versioning

Each snapshot has:

- DatabaseVersion
- SchemaVersion
- PublishedAtUTC
- PublishedBy
- BatchID
- ChecksumSHA256
- ApplicationVersion
- PreviousDatabaseVersion
- RequestCountApplied

Filename pattern:

`IAM_Master_v000042_20260717T160000Z.accdb`

Manifest pattern:

`IAM_Master_v000042_20260717T160000Z.manifest.json`

Never overwrite the only master without retaining the previous version.
