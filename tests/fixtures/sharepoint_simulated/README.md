# Simulated SharePoint Library

This folder represents a local OneDrive/SharePoint-synchronized library for development tests.

Expected database files:

```text
sharepoint_simulated/
├── database/
│   ├── IAM_MASTER.accdb
│   └── snapshots/
│       ├── iam_runtime.sqlite
│       └── iam_runtime.manifest.json
├── requests/
│   ├── pending/
│   ├── imported/
│   ├── approved/
│   ├── rejected/
│   ├── applied/
│   ├── failed/
│   └── quarantine/
├── audit/
├── backups/
├── templates/
├── exports/
└── manifests/
```

The published SQLite snapshot stays inside this simulated SharePoint path. During startup,
the application validates it and synchronizes the working copy to the project-root
`runtime.sqlite`, which is ignored by Git.
