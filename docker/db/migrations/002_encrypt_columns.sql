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
