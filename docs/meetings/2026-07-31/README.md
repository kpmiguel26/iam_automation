# IAM Automation - 8:00 AM Status Review

**Meeting date:** 2026-07-31  
**Purpose:** Present the current implementation status, requirement coverage, open dependencies and next delivery steps.

## Contents

1. [Executive status](./01_EXECUTIVE_STATUS.md)
2. [Requirements status](./02_REQUIREMENTS_STATUS.md)
3. [Technical progress](./03_TECHNICAL_PROGRESS.md)
4. [Gaps, risks and decisions](./04_GAPS_RISKS_AND_DECISIONS.md)
5. [Demo agenda](./05_DEMO_AGENDA.md)

## Current delivery position

The project has a working local application foundation and a functional data-ingestion foundation. The next delivery risk is business-rule validation and source reconciliation, not the web shell.

The application currently runs as a local PySide6 preflight shell with a Flask/Waitress web application, SQLAlchemy ORM, SQLite runtime storage, SharePoint/OneDrive file exchange and JSON-first request workflow.

## Important scope note

This is a development and testing build. Official Fieldglass mappings, source precedence, rehire/blacklist rules, downstream system integrations and production deployment decisions still require stakeholder confirmation.

No live database, employee export, password, or production SharePoint data is included in this meeting package.
