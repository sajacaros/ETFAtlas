-- Enable extensions
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS vector;

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
--   (Change {id, stock_code, stock_name, change_type, before_weight, after_weight, weight_change, detected_at})
--
-- Edges:
--   (ETF)-[:HOLDS {date, weight, shares}]->(Stock)
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

-- ETF Prices (시계열 데이터 - 관계형 테이블이 효율적)
CREATE TABLE IF NOT EXISTS etf_prices (
    etf_code VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    open_price DECIMAL(12, 2),
    high_price DECIMAL(12, 2),
    low_price DECIMAL(12, 2),
    close_price DECIMAL(12, 2),
    volume BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (etf_code, date)
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

-- Vector embeddings for semantic search
CREATE TABLE IF NOT EXISTS etf_embeddings (
    etf_code VARCHAR(20) PRIMARY KEY,
    embedding vector(1536),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_etf_prices_date ON etf_prices(date);
CREATE INDEX IF NOT EXISTS idx_watchlist_items_watchlist_id ON watchlist_items(watchlist_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_items_etf_code ON watchlist_items(etf_code);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO postgres;
