# Portfolio Snapshot Enable/Disable Flag

## Problem
New portfolios get auto-snapshots from Airflow while still being set up. Users need per-portfolio control over snapshot collection.

## Solution
Add `snapshot_enabled` boolean (default false) to portfolios. Users toggle ON after setup is complete.

## Data
- `portfolios.snapshot_enabled BOOLEAN DEFAULT false`

## Backend Changes

### Model/Schema
- `Portfolio` model: add `snapshot_enabled = Column(Boolean, default=False)`
- `PortfolioResponse`, `PortfolioDetailResponse`: add `snapshot_enabled: bool`
- `PortfolioUpdate`: add `snapshot_enabled: Optional[bool]`

### PATCH endpoint behavior
- When `snapshot_enabled` changes from `false` to `true`: immediately create one snapshot using latest `ticker_prices` data
- If no prices available: skip snapshot creation silently (Airflow will pick up next market open)
- Return updated portfolio with new snapshot data if created

### Removals
- `POST /{portfolio_id}/backfill-snapshots` endpoint
- `BackfillSnapshotResponse` schema
- Frontend `backfillSnapshots` API method

### Airflow
- `update_snapshots` in `realtime_prices_rdb.py`: query only portfolios where `snapshot_enabled = true`

## Frontend Changes

### Portfolio card (list view)
- Remove "snapshot creation" button and all backfill-related code
- Add toggle switch at card bottom area
- States:
  - Toggle OFF: show "snapshot disabled" text instead of value
  - Toggle ON + no data: show "snapshot pending"
  - Toggle ON + data: show current value/returns (existing UI)

### Toggle interaction
- Click toggle → call `PATCH /{id}` with `{snapshot_enabled: true/false}`
- On success: refresh portfolio list to reflect new state

## Flow
```
Create portfolio (snapshot_enabled=false)
  → Set up tickers/quantities
  → Toggle ON → server creates immediate snapshot if prices available
    → Success: show value immediately
    → No prices: "auto-created at next market open"
  → Airflow auto-updates every 10min during market hours
```
