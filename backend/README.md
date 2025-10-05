# Delta Strangle Control Plane – Backend

FastAPI service exposing enterprise controls for the BTC/ETH short strangle automation.

## Features

- Configuration CRUD with activation workflow
- Trading lifecycle commands (start/stop/restart) with strategy sessions
- Analytics API returning KPIs and chart feeds
- Async SQLAlchemy storage with SQLite (swap DSN for Postgres in prod)
- Shared trading engine orchestrating Delta Exchange API interactions

## Quickstart

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --port 8001 --reload
```

By default the service reads `DATABASE_URL` from the project `.env`. The sample configuration stores the SQLite file in `../data/delta_trader.db`, which keeps the database on the host filesystem (ideal for bind-mounts when containerizing).

## Testing

```bash
cd backend
pytest
```
