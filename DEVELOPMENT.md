# Development

Use Python 3.10, 3.11, or 3.12 for the POC. Python 3.10 compatibility is required. Do not assume Python 3.13 compatibility with Access ODBC libraries until tested on the target Windows machine.

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
