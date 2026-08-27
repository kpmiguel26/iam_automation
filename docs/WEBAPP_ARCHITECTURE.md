# IAM Automation Webapp Architecture

## Direction

### Current phase: Read-only Employee & Evidence Review

The current release is a read-only review surface over the validated local
runtime SQLite snapshot. Its accepted capabilities are authentication,
employee/profile viewing, source lineage, history, discrepancies, duplicate
evidence, request/audit visibility and read-only exports. It does not update
the canonical employee or publish database changes.

The broader application contains request, approval, ingestion, merge and
publication services. These are future-phase capabilities and must be
disabled, feature-gated or separated before a production read-only release.

The local webapp follows a modular MVC structure while preserving the existing local-only process model:

- **Model/domain:** typed business objects and workflow rules.
- **Repository/infrastructure:** SQLite and future Access/SharePoint adapters.
- **Application services:** use cases, validation, authorization, and transaction boundaries.
- **Web controllers:** Flask routes and request/response mapping.
- **Views:** HTML templates and static branding assets.

Flask is an interface adapter only. It must not write directly to the
published Access database or mutate canonical employee data in the current
phase. The application works against the validated local runtime SQLite
snapshot; publication back to the synchronized route is future-phase only.

## Target Folder Order

```text
iam_automation/
├── application/                  # Use cases and application services
│   └── user_service.py
├── domain/                       # Domain models and business rules
│   └── users.py
├── infrastructure/               # Persistence and external adapters
│   └── sqlite/
│       ├── orm.py                  # SQLAlchemy models, engine and sessions
│       └── user_repository.py
├── interfaces/
│   ├── desktop/                  # PySide6 preflight shell
│   └── web/                      # Flask controllers and web adapters
│       └── user_routes.py
├── database/                     # Schema and database initialization
├── security/                     # Authentication and authorization policies
├── static/                       # Shared application assets
├── templates/                    # Jinja views separated from controllers
├── startup.py                    # Preflight orchestration
├── webapp.py                     # Flask factory and local process boundary
└── qt_startup.py                 # Desktop launcher implementation
```

## Persistence and UI Standards

- SQLAlchemy 2.x is the ORM boundary for runtime SQLite reads and writes.
- `runtime_schema.py` remains the idempotent bootstrap/migration boundary for existing synchronized databases.
- Flask controllers call application services and render Jinja templates; they do not contain SQL or HTML documents.
- Bootstrap 5.3.3 is vendored under `static/vendor/bootstrap/` so the local app works without a CDN connection.
- HTMX 2.0.10 is vendored under `static/vendor/htmx/` for progressive AJAX-style HTML fragment updates; no additional runtime server is required.
- Shared notifications are stored as one JSON event per notification under the synchronized `notifications/` folder. Each event contains an immutable recipient snapshot and a per-user `read_by`/`resolved_by` marker, so read state does not depend on publishing `runtime.sqlite` and newly added users do not inherit the historical backlog.
- Brand-specific styling is limited to `static/css/app.css`.
- Role forms use controlled multi-select values with human-readable labels; controllers never trust free-text role names from the browser.
- The workstation/VDI identity is recorded for traceability and audit only. It does not carry an application password, application roles or an approval gate. Application authorization is evaluated after the separate IAM account login.

## First Web Module: User Administration

The first CRUD module uses the local `runtime.sqlite` database and supports:

- List application accounts.
- Create an application account with a hashed password.
- Update display name and roles.
- Reset a password without exposing the previous password.
- Activate or deactivate an account through a soft status change.

Only an authenticated `APPLICATION_ADMIN` or `MASTER_ADMIN` may access `/admin/users`. The legacy `ADMINISTRATOR` value is normalized as the application-admin alias. User changes are local SQLite changes in this increment. Snapshot publication, backup, audit event integration, and approval workflow are the next controls to add before treating administrative CRUD as production-ready.

## Request Flow

```text
Browser
  -> Flask route/controller
  -> UserService
  -> UserRepository
  -> local runtime.sqlite
```

The controller does not contain SQL or password hashing. The repository does not decide permissions. The service owns validation and password hashing, keeping the boundaries ready for the remaining CRUD modules: requests, approvals, templates, workers, exports, and audit.

## Windows Identity Traceability Flow

```text
Workstation identity
  -> preflight detects username and computer
  -> append-only audit event
  -> application login with IAM account
  -> application roles and permissions
```

The legacy `approved_users` table and identity-discovery JSON remain available for historical compatibility and future policy decisions, but they are not consulted by the current preflight authorization path. The Windows identity is evidence of the local execution context; the IAM application account is the authorization subject.
