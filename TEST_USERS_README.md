# IAM Automation Test Users

These accounts are for local development and QA only. They are not production credentials and must not be reused outside the test workspace.

## Test Accounts

| Username | Password | Role | Purpose |
|---|---|---|---|
| `master.admin` | Set locally | Master Administrator | Test global settings, audit, recovery, session revocation and break-glass controls. |
| `iam.admin` | Set locally | Application Administrator | Test users, requests, approvals, notifications, delegations and imports. |
| `requester.test` | Set locally | Requester | Test request creation and requester-only access. |
| `reviewer.test` | Set locally | Reviewer | Test approval queue and review decisions. |
| `writer.test` | Set locally | Data Publisher | Test approved publication workflows. |
| `auditor.test` | Set locally | Auditor | Test read-only audit and evidence access. |

The test suite also uses `app-user` with a test-only password in an injected authenticator. That account is not automatically present in the runtime database.

## Create The Accounts

Run the following command once per account. The script prompts for the password and stores only a password hash in SQLite.

macOS/Linux:

```bash
./.venv/bin/python scripts/create_app_user.py --path runtime.sqlite --username master.admin --role MASTER_ADMIN
./.venv/bin/python scripts/create_app_user.py --path runtime.sqlite --username iam.admin --role APPLICATION_ADMIN
./.venv/bin/python scripts/create_app_user.py --path runtime.sqlite --username requester.test --role REQUESTER
./.venv/bin/python scripts/create_app_user.py --path runtime.sqlite --username reviewer.test --role REVIEWER
./.venv/bin/python scripts/create_app_user.py --path runtime.sqlite --username writer.test --role WRITER
./.venv/bin/python scripts/create_app_user.py --path runtime.sqlite --username auditor.test --role AUDITOR
```

Windows:

```bat
.venv\Scripts\python.exe scripts\create_app_user.py --path runtime.sqlite --username master.admin --role MASTER_ADMIN
.venv\Scripts\python.exe scripts\create_app_user.py --path runtime.sqlite --username iam.admin --role APPLICATION_ADMIN
.venv\Scripts\python.exe scripts\create_app_user.py --path runtime.sqlite --username requester.test --role REQUESTER
.venv\Scripts\python.exe scripts\create_app_user.py --path runtime.sqlite --username reviewer.test --role REVIEWER
.venv\Scripts\python.exe scripts\create_app_user.py --path runtime.sqlite --username writer.test --role WRITER
.venv\Scripts\python.exe scripts\create_app_user.py --path runtime.sqlite --username auditor.test --role AUDITOR
```

When the SharePoint-simulated fixture is being used, publish the local runtime snapshot after creating or changing test accounts:

```bash
./.venv/bin/python scripts/sync_runtime_database.py tests/fixtures/sharepoint_simulated --publish
```

Windows:

```bat
.venv\Scripts\python.exe scripts\sync_runtime_database.py tests\fixtures\sharepoint_simulated --publish
```

## Login Model

1. Preflight detects the Windows/VDI identity and records it for traceability.
2. The Windows identity does not provide application roles or a password.
3. The web login uses one of the IAM application accounts listed above.
4. The application role controls the dashboard and protected routes.

## Reset A Test Password

Run the same `create_app_user.py` command again for the username. Enter the new password when prompted. The existing account is updated and remains assigned to its selected role.

## Safety

- Passwords are intentionally not documented or committed. Set them locally when the account is created.
- Do not commit plaintext passwords or reuse test passwords outside the test workspace.
- Runtime SQLite and published snapshots are development fixtures only; replace them before production deployment.
- Do not use these credentials in a shared, production or customer environment.
- Replace all test passwords before any production deployment.
