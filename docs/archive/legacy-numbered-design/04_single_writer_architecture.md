# Single-Writer Architecture

The system uses immutable request files and an Administrator/Writer batch process.

```text
User Applications
  -> immutable JSON requests
SharePoint requests/pending
  -> imported by Administrator/Writer
Local Access working copy outside OneDrive
  -> approval and validation
Versioned Access snapshot
  -> SharePoint publication
```

Only Administrator/Writer roles can apply approved changes and publish snapshots.
