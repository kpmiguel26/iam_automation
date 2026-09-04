# Rejected Architectures

## Direct Multi-User Access Editing

Rejected because OneDrive sync is not transactional and Access lock files do not prevent SharePoint conflict copies or stale overwrite.

## SQLite in OneDrive

Rejected as a primary fix because SQLite remains a file-based database subject to stale copy and sync conflict behavior.

## Central Coordinator Service

Rejected because no server, VM, API host, or Windows Service host exists.

## Distributed Lock File as Sole Control

Rejected because a lock file in OneDrive is advisory only and cannot guarantee distributed mutual exclusion.

## Full Database Replacement by Every Client

Rejected because it creates competing master versions.
