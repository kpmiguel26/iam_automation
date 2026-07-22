# Development

Use Python 3.10 or newer for the POC. Python 3.10 compatibility is required; newer versions are accepted by the launchers. Validate Microsoft Access ODBC compatibility separately on the target Windows machine.

Install:

```bash
python -m pip install -r requirements.txt
```

Run tests:

```bash
python -m pytest
```

Code conventions:

- Keep master database writes behind the administrator batch workflow.
- Client-side requesters must submit immutable JSON request files.
- Prefer `pathlib`.
- Treat SharePoint URLs as invalid runtime paths; use local OneDrive-synced paths.
- Keep local working copies outside OneDrive.
- Do not store plaintext passwords.
- Do not introduce a central API, persistent service, server, VM, Docker, or database engine in the current architecture.
- The local PySide6 launcher and loopback-only Flask webapp are allowed as presentation components. They must bind only to `127.0.0.1` and must not become a shared service.
