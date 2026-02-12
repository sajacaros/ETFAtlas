-- Enable extensions
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Load AGE
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Create graph for ETF relationships
SELECT create_graph('etf_graph');

-- Reset search path
SET search_path = public;

-- =====================================================
-- Apache AGE Graph Structure:
--
-- Nodes:
--   (ETF {code, name, updated_at})
--   (Stock {code, name})
--   (Price {date, open, high, low, close, volume, nav, market_cap, net_assets, trade_value, change_rate})
--   (Change {id, stock_code, stock_name, change_type, before_weight, after_weight, weight_change, detected_at})
--
-- Edges:
--   (ETF)-[:HOLDS {date, weight, shares}]->(Stock)
--   (ETF)-[:HAS_PRICE]->(Price)
--   (Stock)-[:HAS_PRICE]->(Price)
--   (ETF)-[:HAS_CHANGE]->(Change)
-- =====================================================

-- =====================================================
-- Relational Tables (시계열/사용자 데이터)
-- =====================================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    picture VARCHAR(512),
    google_id VARCHAR(255) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ETFs (전체 ETF 메타데이터 - 검색용)
CREATE TABLE IF NOT EXISTS etfs (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    issuer VARCHAR(255),
    category VARCHAR(100),
    net_assets BIGINT,
    expense_ratio NUMERIC(5, 4),
    inception_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Watchlists
CREATE TABLE IF NOT EXISTS watchlists (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL DEFAULT 'My Watchlist',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Watchlist items (ETF code 직접 참조)
CREATE TABLE IF NOT EXISTS watchlist_items (
    id SERIAL PRIMARY KEY,
    watchlist_id INTEGER REFERENCES watchlists(id) ON DELETE CASCADE,
    etf_code VARCHAR(20) NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(watchlist_id, etf_code)
);

-- Portfolios (사용자 포트폴리오)
CREATE TABLE IF NOT EXISTS portfolios (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL DEFAULT 'My Portfolio',
    calculation_base VARCHAR(20) NOT NULL DEFAULT 'CURRENT_TOTAL',
    target_total_amount DECIMAL(15, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Target Allocations (목표 비중)
CREATE TABLE IF NOT EXISTS target_allocations (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id) ON DELETE CASCADE,
    ticker VARCHAR(20) NOT NULL,
    target_weight DECIMAL(7, 4) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(portfolio_id, ticker)
);

-- Holdings (실제 보유)
CREATE TABLE IF NOT EXISTS holdings (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id) ON DELETE CASCADE,
    ticker VARCHAR(20) NOT NULL,
    quantity DECIMAL(15, 4) NOT NULL DEFAULT 0,
    avg_price NUMERIC(12, 2) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(portfolio_id, ticker)
);

-- Portfolio Snapshots (포트폴리오 일별 스냅샷)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    total_value DECIMAL(15, 2) NOT NULL,
    prev_value DECIMAL(15, 2),
    change_amount DECIMAL(15, 2),
    change_rate DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_portfolio_snapshot_date UNIQUE (portfolio_id, date)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_watchlist_items_watchlist_id ON watchlist_items(watchlist_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_items_etf_code ON watchlist_items(etf_code);
CREATE INDEX IF NOT EXISTS idx_portfolios_user_id ON portfolios(user_id);
CREATE INDEX IF NOT EXISTS idx_target_allocations_portfolio_id ON target_allocations(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_holdings_portfolio_id ON holdings(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_etfs_name_trgm ON etfs USING GIN (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_etfs_code_trgm ON etfs USING GIN (code gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_portfolio_id ON portfolio_snapshots(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_date ON portfolio_snapshots(date);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO postgres;
