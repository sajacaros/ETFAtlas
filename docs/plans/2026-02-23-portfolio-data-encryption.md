# Portfolio Data Encryption Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Encrypt sensitive portfolio columns (amounts, quantities, rates) at the application level using AES-256-GCM so DB access alone cannot reveal financial data.

**Architecture:** SQLAlchemy `TypeDecorator` classes transparently encrypt/decrypt `Decimal` and `float` values. Encryption key stored as environment variable. DB columns change from `DECIMAL`/`FLOAT` to `TEXT` (Base64-encoded ciphertext). Airflow DAG uses shared encryption utility.

**Tech Stack:** Python `cryptography` library (already a transitive dep of `python-jose[cryptography]`), SQLAlchemy TypeDecorator, AES-256-GCM

---

### Task 1: Add ENCRYPTION_KEY to config and environment

**Files:**
- Modify: `backend/app/config.py:5-12`
- Modify: `.env.example:8-9`

**Step 1: Add encryption_key field to Settings**

In `backend/app/config.py`, add after line 11 (`jwt_expire_minutes`):

```python
    # Encryption
    encryption_key: str = ""  # 32-byte hex key for AES-256-GCM
```

**Step 2: Add ENCRYPTION_KEY to .env.example**

After the `JWT_SECRET` line, add:

```
ENCRYPTION_KEY=your-encryption-key-change-in-production
```

**Step 3: Generate a real key for .env**

Run: `python -c "import os; print(os.urandom(32).hex())"` and add the result to `.env` as `ENCRYPTION_KEY=<generated_hex>`.

**Step 4: Commit**

```bash
git add backend/app/config.py .env.example
git commit -m "feat: add ENCRYPTION_KEY config for portfolio data encryption"
```

---

### Task 2: Create encryption utility module

**Files:**
- Create: `backend/app/utils/encryption.py`

**Step 1: Create the encryption module**

```python
"""Application-level AES-256-GCM column encryption for SQLAlchemy."""
import base64
import os
from decimal import Decimal, InvalidOperation
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text, String
from sqlalchemy.types import TypeDecorator


def _get_key() -> bytes:
    from ..config import get_settings
    key_hex = get_settings().encryption_key
    if not key_hex:
        raise RuntimeError("ENCRYPTION_KEY is not set")
    return bytes.fromhex(key_hex)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value and return Base64-encoded ciphertext."""
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
    # Store as nonce + ciphertext, base64 encoded
    return base64.b64encode(nonce + ciphertext).decode('ascii')


def decrypt_value(token: str) -> str:
    """Decrypt a Base64-encoded ciphertext and return the plaintext string."""
    key = _get_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(token)
    nonce = raw[:12]
    ciphertext = raw[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode('utf-8')


class EncryptedDecimal(TypeDecorator):
    """Transparently encrypts/decrypts Decimal values."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_value(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        plaintext = decrypt_value(value)
        return Decimal(plaintext)


class EncryptedFloat(TypeDecorator):
    """Transparently encrypts/decrypts float values."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_value(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        plaintext = decrypt_value(value)
        return float(plaintext)
```

**Step 2: Commit**

```bash
git add backend/app/utils/encryption.py
git commit -m "feat: add AES-256-GCM encryption utility with SQLAlchemy TypeDecorators"
```

---

### Task 3: Update SQLAlchemy models to use encrypted types

**Files:**
- Modify: `backend/app/models/portfolio.py`

**Step 1: Update imports and column types**

Replace the imports line (line 1):
```python
from sqlalchemy import Column, Integer, String, DateTime, Date, Float, ForeignKey, Numeric, UniqueConstraint
```
with:
```python
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, UniqueConstraint
```

Add import after line 4:
```python
from ..utils.encryption import EncryptedDecimal, EncryptedFloat
```

**Step 2: Update Holding columns (lines 46-47)**

Change:
```python
    quantity = Column(Numeric(15, 4), nullable=False, default=0)
    avg_price = Column(Numeric(12, 2), nullable=True)
```
to:
```python
    quantity = Column(EncryptedDecimal, nullable=False, default=0)
    avg_price = Column(EncryptedDecimal, nullable=True)
```

**Step 3: Update PortfolioSnapshot columns (lines 60-63)**

Change:
```python
    total_value = Column(Numeric(15, 2), nullable=False)
    prev_value = Column(Numeric(15, 2), nullable=True)
    change_amount = Column(Numeric(15, 2), nullable=True)
    change_rate = Column(Float, nullable=True)
```
to:
```python
    total_value = Column(EncryptedDecimal, nullable=False)
    prev_value = Column(EncryptedDecimal, nullable=True)
    change_amount = Column(EncryptedDecimal, nullable=True)
    change_rate = Column(EncryptedFloat, nullable=True)
```

**Step 4: Note — `Numeric` and `Float` imports removed**

`Numeric` is still used in `Portfolio.target_total_amount` and `TargetAllocation.target_weight`. Add `Numeric` back to the sqlalchemy import. `Float` is no longer needed.

Updated import:
```python
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Numeric, UniqueConstraint
```

**Step 5: Commit**

```bash
git add backend/app/models/portfolio.py
git commit -m "feat: use EncryptedDecimal/EncryptedFloat for sensitive portfolio columns"
```

---

### Task 4: Refactor get_total_dashboard to use app-level aggregation

**Files:**
- Modify: `backend/app/routers/portfolio.py:365-390`

**Step 1: Replace the DB-level func.sum with app-level aggregation**

The current `get_total_dashboard()` (lines 365-390) uses `func.sum(PortfolioSnapshot.total_value)`. Encrypted columns can't be summed in SQL. Replace with fetching all rows and aggregating in Python.

Replace lines 374-390 with:

```python
    # Fetch all snapshots for user's portfolios (encrypted columns need app-level aggregation)
    all_snapshots = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.portfolio_id.in_(portfolio_ids),
    ).order_by(PortfolioSnapshot.date.asc()).all()

    # Group by date and sum total_value in Python
    from collections import defaultdict
    date_agg: dict[date, dict] = {}
    for s in all_snapshots:
        key = s.date
        if key not in date_agg:
            date_agg[key] = {'total_value': Decimal('0'), 'updated_at': s.updated_at}
        date_agg[key]['total_value'] += Decimal(str(s.total_value))
        if s.updated_at and (date_agg[key]['updated_at'] is None or s.updated_at > date_agg[key]['updated_at']):
            date_agg[key]['updated_at'] = s.updated_at

    class SnapshotRow:
        def __init__(self, d, tv, ua=None):
            self.date = d
            self.total_value = tv
            self.updated_at = ua

    snapshots = [
        SnapshotRow(d, agg['total_value'], agg['updated_at'])
        for d, agg in sorted(date_agg.items())
    ]
    return _build_dashboard_response(snapshots)
```

Also remove the now-unused `func` import from sqlalchemy if no longer needed. Check: `func.max(Portfolio.display_order)` is still used in `create_portfolio()` (line 140), so keep `func` in imports.

**Step 2: Commit**

```bash
git add backend/app/routers/portfolio.py
git commit -m "refactor: replace SQL-level SUM with app-level aggregation for encrypted columns"
```

---

### Task 5: Update Airflow DAG to use encryption

**Files:**
- Modify: `airflow/dags/realtime_prices_rdb.py:176-255`

**Step 1: Add encryption to update_snapshots**

The Airflow DAG uses raw `psycopg2` to INSERT into `portfolio_snapshots`. Since the columns are now TEXT (encrypted), we need to encrypt values before writing and decrypt when reading.

Add encryption helper import at top of `update_snapshots()`:

```python
def update_snapshots(**context):
    """ticker_prices 기반으로 포트폴리오 스냅샷 갱신."""
    import sys, os
    # Add backend to path for encryption utility
    backend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'backend')
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from app.utils.encryption import encrypt_value
```

**Step 2: Encrypt values before INSERT**

In the `update_snapshots` function, wrap the values being written:

Change the value computation section (after calculating `total_value`, `prev_value`, `change_amount`, `change_rate`):

```python
            # Encrypt values before storing
            enc_total = encrypt_value(str(total_value))
            enc_prev = encrypt_value(str(prev_value)) if prev_value is not None else None
            enc_change_amt = encrypt_value(str(change_amount)) if change_amount is not None else None
            enc_change_rate = encrypt_value(str(change_rate)) if change_rate is not None else None
```

And update the UPSERT query to use the encrypted values:

```python
            cur.execute("""
                INSERT INTO portfolio_snapshots
                    (portfolio_id, date, total_value, prev_value,
                     change_amount, change_rate, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (portfolio_id, date)
                DO UPDATE SET
                    total_value = EXCLUDED.total_value,
                    prev_value = EXCLUDED.prev_value,
                    change_amount = EXCLUDED.change_amount,
                    change_rate = EXCLUDED.change_rate
            """, (pid, today_str, enc_total, enc_prev,
                  enc_change_amt, enc_change_rate))
```

**Step 3: Decrypt prev_value when reading for change calculation**

The DAG reads `total_value` from previous snapshots to compute change. Since it's now encrypted:

```python
            cur.execute("""
                SELECT total_value FROM portfolio_snapshots
                WHERE portfolio_id = %s AND date < %s
                ORDER BY date DESC LIMIT 1
            """, (pid, today_str))
            prev = cur.fetchone()
            if prev and prev[0]:
                from app.utils.encryption import decrypt_value
                prev_value = Decimal(decrypt_value(prev[0]))
            else:
                prev_value = None
```

**Step 4: Commit**

```bash
git add airflow/dags/realtime_prices_rdb.py
git commit -m "feat: encrypt/decrypt portfolio snapshot values in Airflow DAG"
```

---

### Task 6: Create DB migration SQL script

**Files:**
- Create: `docker/db/migrations/002_encrypt_columns.sql`
- Modify: `docker/db/init/01_extensions.sql:80-104`

**Step 1: Create migration script for existing deployments**

```sql
-- Migration: Change sensitive columns from DECIMAL/FLOAT to TEXT for encryption
-- Run this AFTER updating the application code

-- portfolio_snapshots
ALTER TABLE portfolio_snapshots
    ALTER COLUMN total_value TYPE TEXT USING total_value::TEXT,
    ALTER COLUMN prev_value TYPE TEXT USING prev_value::TEXT,
    ALTER COLUMN change_amount TYPE TEXT USING change_amount::TEXT,
    ALTER COLUMN change_rate TYPE TEXT USING change_rate::TEXT;

-- holdings
ALTER TABLE holdings
    ALTER COLUMN quantity TYPE TEXT USING quantity::TEXT,
    ALTER COLUMN avg_price TYPE TEXT USING avg_price::TEXT;
```

**Step 2: Update init SQL for fresh deployments**

In `docker/db/init/01_extensions.sql`, change the `holdings` table (lines 83-89):

```sql
    quantity TEXT NOT NULL DEFAULT '0',
    avg_price TEXT DEFAULT NULL,
```

And the `portfolio_snapshots` table (lines 97-100):

```sql
    total_value TEXT NOT NULL,
    prev_value TEXT,
    change_amount TEXT,
    change_rate TEXT,
```

**Step 3: Commit**

```bash
git add docker/db/migrations/002_encrypt_columns.sql docker/db/init/01_extensions.sql
git commit -m "feat: update DB schema for encrypted TEXT columns"
```

---

### Task 7: Create data migration script for existing data

**Files:**
- Create: `scripts/migrate_encrypt.py`

**Step 1: Create migration script**

This script reads existing plaintext data, encrypts it, and writes it back. Must be run once after deploying code changes and running the SQL migration.

```python
"""One-time migration: encrypt existing plaintext data in portfolio_snapshots and holdings."""
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import psycopg2
from app.utils.encryption import encrypt_value

DB_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:9602/etf_atlas')


def parse_db_url(url):
    url = url.replace('postgresql://', '')
    auth, host_db = url.split('@')
    user, password = auth.split(':')
    host_port, database = host_db.split('/')
    if ':' in host_port:
        host, port = host_port.split(':')
    else:
        host, port = host_port, 5432
    return dict(host=host, port=int(port), database=database, user=user, password=password)


def migrate():
    conn = psycopg2.connect(**parse_db_url(DB_URL))
    cur = conn.cursor()

    # Migrate portfolio_snapshots
    cur.execute("SELECT id, total_value, prev_value, change_amount, change_rate FROM portfolio_snapshots")
    rows = cur.fetchall()
    print(f"Migrating {len(rows)} snapshots...")
    for row_id, tv, pv, ca, cr in rows:
        # Skip if already encrypted (not a valid number)
        try:
            float(tv)
        except (ValueError, TypeError):
            continue
        enc_tv = encrypt_value(str(tv)) if tv is not None else None
        enc_pv = encrypt_value(str(pv)) if pv is not None else None
        enc_ca = encrypt_value(str(ca)) if ca is not None else None
        enc_cr = encrypt_value(str(cr)) if cr is not None else None
        cur.execute(
            "UPDATE portfolio_snapshots SET total_value=%s, prev_value=%s, change_amount=%s, change_rate=%s WHERE id=%s",
            (enc_tv, enc_pv, enc_ca, enc_cr, row_id)
        )

    # Migrate holdings
    cur.execute("SELECT id, quantity, avg_price FROM holdings")
    rows = cur.fetchall()
    print(f"Migrating {len(rows)} holdings...")
    for row_id, qty, ap in rows:
        try:
            float(qty)
        except (ValueError, TypeError):
            continue
        enc_qty = encrypt_value(str(qty)) if qty is not None else None
        enc_ap = encrypt_value(str(ap)) if ap is not None else None
        cur.execute(
            "UPDATE holdings SET quantity=%s, avg_price=%s WHERE id=%s",
            (enc_qty, enc_ap, row_id)
        )

    conn.commit()
    cur.close()
    conn.close()
    print("Migration complete.")


if __name__ == '__main__':
    migrate()
```

**Step 2: Commit**

```bash
git add scripts/migrate_encrypt.py
git commit -m "feat: add one-time data encryption migration script"
```

---

### Task 8: Update Airflow docker/environment to include ENCRYPTION_KEY

**Files:**
- Check: `docker-compose.yml` or `docker-compose.yaml` for Airflow service environment

**Step 1: Ensure ENCRYPTION_KEY is passed to Airflow container**

Check the docker-compose file. The Airflow service needs `ENCRYPTION_KEY` in its environment. Add it alongside other env vars. Also ensure the backend path is accessible or the encryption utility is available.

**Step 2: Commit if changes are needed**

```bash
git add docker-compose.yml
git commit -m "feat: pass ENCRYPTION_KEY to Airflow container"
```

---

### Task 9: Verify and test end-to-end

**Step 1: Rebuild containers**

```bash
docker compose up -d --build backend
```

**Step 2: Run SQL migration on existing DB**

```bash
docker compose exec db psql -U postgres -d etf_atlas -f /path/to/002_encrypt_columns.sql
```

Or apply manually via psql.

**Step 3: Run data migration script**

```bash
ENCRYPTION_KEY=<your-key> DATABASE_URL=postgresql://postgres:postgres@localhost:9602/etf_atlas python scripts/migrate_encrypt.py
```

**Step 4: Verify encrypted data in DB**

```bash
docker compose exec db psql -U postgres -d etf_atlas -c "SELECT total_value FROM portfolio_snapshots LIMIT 3;"
```

Expected: Base64 strings instead of numeric values.

**Step 5: Verify API still works**

```bash
curl -H "Authorization: Bearer <token>" http://localhost:9601/api/portfolios/
curl -H "Authorization: Bearer <token>" http://localhost:9601/api/portfolios/dashboard/total
```

Expected: Normal JSON responses with numeric values (decrypted by the app).

**Step 6: Verify Airflow DAG**

Trigger the DAG manually and check that new snapshots are written encrypted.

**Step 7: Commit any fixes**

```bash
git commit -m "fix: adjustments from end-to-end encryption testing"
```
