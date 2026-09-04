# Security Model

Initial identity: Windows username and computer name.

Roles:

- `REQUESTER`
- `REVIEWER`
- `ADMINISTRATOR`
- `WRITER`
- `AUDITOR`

Authorization source options:

- Access approved-user tables.
- Controlled configuration.
- SharePoint-managed user list.
- Future Microsoft Entra ID.

Windows username capture is not strong authentication by itself unless domain and workstation controls guarantee identity.
