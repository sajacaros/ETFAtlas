-- Portfolio sharing columns (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'portfolios' AND column_name = 'is_shared'
    ) THEN
        ALTER TABLE portfolios ADD COLUMN is_shared BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'portfolios' AND column_name = 'share_token'
    ) THEN
        ALTER TABLE portfolios ADD COLUMN share_token UUID UNIQUE DEFAULT NULL;
    END IF;
END $$;
