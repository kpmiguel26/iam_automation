# Security Model

The initial identity signal is the current Windows username and computer name. This is not equivalent to strong centralized authentication unless the environment guarantees domain identity and workstation controls.

Authorization is validated through an approved-user source. Candidate sources:

- Access `tbl_Users` and role tables.
- Signed or controlled configuration file.
- SharePoint-managed user list.
- Future Microsoft Entra ID integration.

Roles:

- `REQUESTER`: create immutable requests and view own status.
- `REVIEWER`: review requests and recommend approval or rejection.
- `ADMINISTRATOR` / `WRITER`: import, approve, apply, publish, recover, export.
- `AUDITOR`: read-only audit and version review.

Plaintext passwords are not stored.

Request files must contain only fields required for the requested change. Sensitive employee data should be minimized, protected by SharePoint permissions, and covered by retention rules.
