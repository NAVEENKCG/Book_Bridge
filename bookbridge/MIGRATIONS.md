# Database Migrations with Alembic

## Setup (already done)
```
alembic init alembic          # creates alembic/ + alembic.ini
alembic stamp head            # marks existing DB as up-to-date
```

## Day-to-day workflow

### 1 — Edit your models in `models.py`

Change a column, add a table, rename a field, etc.

### 2 — Auto-generate a migration

```bash
alembic revision --autogenerate -m "describe_what_changed"
```

A new file appears in `alembic/versions/`. **Always review it before applying.**

### 3 — Apply the migration

```bash
alembic upgrade head
```

### Other useful commands

| Command | What it does |
|---------|-------------|
| `alembic current` | Shows which revision the DB is on |
| `alembic history --verbose` | Lists all revisions |
| `alembic upgrade head` | Migrate to latest |
| `alembic downgrade -1` | Roll back one revision |
| `alembic downgrade base` | Roll ALL the way back |
| `alembic upgrade <rev>` | Migrate to a specific revision |

## Notes
- `alembic.ini` → `sqlalchemy.url` is the fallback; `env.py` overrides it with `DATABASE_URL` from `.env`.
- SQLite doesn't support `ALTER COLUMN` or `DROP COLUMN` natively — Alembic works around this with `batch_alter_table` for SQLite. If you hit those cases, enable `render_as_batch=True` in `env.py`.
- On Render (PostgreSQL), all ALTER operations work fine.
