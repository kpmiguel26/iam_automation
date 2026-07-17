# Administrator Guide

Administrators process request batches. They do not edit the SharePoint-synced Access file in place.

## Daily Batch Procedure

1. Confirm OneDrive sync is complete.
2. Confirm no other writer is processing a batch.
3. Run environment validation.
4. Import pending requests.
5. Review quarantined and duplicate files.
6. Approve or reject valid requests.
7. Apply approved requests to a local Access copy.
8. Validate database integrity and record versions.
9. Generate official provisioning Excel templates.
10. Publish a versioned Access snapshot and manifest.
11. Archive request files after successful publication.
12. Store batch summary and audit events.

Publication must abort if the published database version or checksum changed after the batch started.
