# IAM Automation Webapp Architecture

## Direction

The local webapp follows a modular MVC structure while preserving the existing local-only process model:

- **Model/domain:** typed business objects and workflow rules.
- **Repository/infrastructure:** SQLite and future Access/SharePoint adapters.
- **Application services:** use cases, validation, authorization, and transaction boundaries.
- **Web controllers:** Flask routes and request/response mapping.
- **Views:** HTML templates and static branding assets.

Flask is an interface adapter only. It must not write directly to the published Access database. The application works against the validated local runtime SQLite snapshot; publication back to the synchronized route remains an explicit controlled operation.

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
- Brand-specific styling is limited to `static/css/app.css`.
- Role forms use controlled multi-select values with human-readable labels; controllers never trust free-text role names from the browser.
- Newly discovered workstation identities are written to `database/snapshots/iam_identity_discovery.json` as pending requests. Strict mode requires admin approval before `approved_users` is updated.

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

## Identity Discovery Flow

```text
Workstation identity
  -> identity discovery JSON (PENDING)
  -> Admin Control Center notification
  -> Master/Application Admin review
  -> approved_users + user roles
  -> identity discovery JSON (APPROVED)
```

The JSON is a synchronized request queue, not an authorization database. It is deduplicated by normalized username and includes the discovery computer, suggested role, status, timestamps and processing actor. Development auto-approval is retained only for local testing; strict mode leaves the request pending and blocks the unknown identity.
