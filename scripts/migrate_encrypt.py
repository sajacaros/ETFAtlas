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
