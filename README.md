# CRM Python App Structure

Python desktop CRM skeleton for the Access CRM migration.

This project is only a structural skeleton. It does not create PostgreSQL tables, does not migrate data, and does not implement full screens yet.

## Planned Stack

- GUI: PySide6
- Database: PostgreSQL
- Database access: SQLAlchemy 2.x with psycopg
- Configuration: `.env`

## Run Later

Install dependencies after the schema and implementation plan are approved:

```powershell
py -3.11 -m pip install -r requirements.txt
py -3.11 -m app.main
```

## Current Status

- Folder structure is created.
- Layer boundaries are represented.
- Business logic and UI files are placeholders.
- No real database connection is opened by default.
