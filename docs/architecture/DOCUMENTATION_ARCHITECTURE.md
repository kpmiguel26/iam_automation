# Documentation Architecture

## Purpose

Make project status, requirements, implementation work and evidence easy to
find without moving historical records or breaking links.

## Canonical hierarchy

```text
docs/
├── README.md                 # navigation hub
├── STATUS.md                 # status registry and story index
├── bugs/                     # confirmed defects and verification
├── features/                 # feature briefs and story acceptance criteria
├── work/                     # plans and execution slices
├── pending/                  # unresolved decisions/dependencies
├── architecture/             # system/documentation architecture
├── meetings/                 # immutable meeting records
├── uat/                      # UAT scenarios and decision questions
└── work_tracking/            # backlog, decisions and bitacora
```

## Lifecycle

`Meeting or discovery → feature/bug record → work plan → implementation → tests
and evidence → STATUS update → bitacora entry → pending closure or deferral`.

## Required metadata

Every active feature or bug document must include ID, title, status, priority,
owner, target/date, source references and exit criteria. Every user story must
have a stable ID and one of the status values in `STATUS.md`.

## Reference rules

- Use relative Markdown links inside `docs/`.
- Link meeting notes as the source, feature/bug docs as the scope, work docs as
  execution, and tests/code as evidence.
- Keep historical meeting and evidence files immutable.
- Use `STATUS.md` as the cross-document registry; do not maintain a second
  conflicting status table.
- Keep unresolved business decisions in `pending/` and link them from the
  relevant feature.
- Record meaningful implementation changes in `work_tracking/BITACORA.md`.

## Scope rule

Documentation organization does not change product scope. The current release
remains read-only with respect to authoritative source systems; any writer,
merge, approval or publication capability requires an explicit future-phase
decision.
