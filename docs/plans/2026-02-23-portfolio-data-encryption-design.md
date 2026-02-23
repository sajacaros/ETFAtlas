# Portfolio Data Encryption Design

## Problem
DB 관리자나 내부자가 직접 DB에 접속하면 사용자의 포트폴리오 금액/수량 데이터를 평문으로 볼 수 있음.

## Goal
민감 컬럼(금액, 수량, 비율)을 애플리케이션 레벨에서 AES-256-GCM으로 암호화하여 DB에는 암호문만 저장.

## Approach: Application-Level Column Encryption (AES-256-GCM)

### Encryption Flow
```
Write: Python value → AES-GCM encrypt → Base64 encode → DB TEXT column
Read:  DB TEXT column → Base64 decode → AES-GCM decrypt → Python value
```

- Algorithm: AES-256-GCM (authenticated encryption with integrity)
- Key: 32-byte random key stored as `ENCRYPTION_KEY` environment variable
- Library: `cryptography` (already a transitive dependency via python-jose)
- Implementation: SQLAlchemy `TypeDecorator` for transparent encrypt/decrypt

### Encrypted Columns

| Table | Column | Current Type | Encrypted Type |
|-------|--------|-------------|----------------|
| portfolio_snapshots | total_value | DECIMAL(15,2) | EncryptedDecimal (TEXT) |
| portfolio_snapshots | prev_value | DECIMAL(15,2) | EncryptedDecimal (TEXT) |
| portfolio_snapshots | change_amount | DECIMAL(15,2) | EncryptedDecimal (TEXT) |
| portfolio_snapshots | change_rate | DOUBLE PRECISION | EncryptedFloat (TEXT) |
| holdings | quantity | DECIMAL(15,4) | EncryptedDecimal (TEXT) |
| holdings | avg_price | DECIMAL(12,2) | EncryptedDecimal (TEXT) |

### Code Changes

1. **New**: `backend/app/utils/encryption.py` — EncryptedDecimal, EncryptedFloat TypeDecorators
2. **Modify**: `backend/app/models/portfolio.py` — swap column types
3. **Modify**: `backend/app/config.py` — add ENCRYPTION_KEY setting
4. **Modify**: `backend/app/routers/portfolio.py` — change `func.sum()` in `get_total_dashboard()` to app-level aggregation
5. **Modify**: `airflow/dags/realtime_prices_rdb.py` — use encryption when writing snapshots
6. **New**: `scripts/migrate_encrypt.py` — one-time migration script for existing data
7. **Modify**: `docker/db/init/01_extensions.sql` — change column types to TEXT
8. **Modify**: `.env.example` — add ENCRYPTION_KEY placeholder

### Query Impact
- `get_total_dashboard()`: currently uses `func.sum(total_value)` → must fetch all rows, decrypt, sum in Python
- All other queries: transparent via TypeDecorator, no code changes needed

### Data Migration Strategy
1. Add new TEXT columns alongside existing DECIMAL columns
2. Run migration script: read plaintext → encrypt → write to new columns
3. Drop old columns, rename new columns
4. Alternative (simpler for dev): truncate + rebuild snapshots via backfill

### Security Properties
- DB dump/access reveals only Base64 ciphertext
- Each value encrypted with unique nonce (IV) — same plaintext produces different ciphertext
- GCM mode provides authentication — tampered ciphertext detected on decryption
- Key stored only in application environment, not in DB

### Limitations
- No DB-level aggregation/sorting on encrypted columns
- Key rotation requires full data re-encryption
- Key compromise exposes all data (single master key, not per-user)
