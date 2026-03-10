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
--   (ETF {code, name, updated_at, net_assets, expense_ratio})
--   (Stock {code, name})
--   (Price {date, open, high, low, close, volume, nav, market_cap, net_assets, trade_value, change_rate})
--   (User {user_id})
--
-- Edges:
--   (ETF)-[:HOLDS {date, weight, shares}]->(Stock)
--   (ETF)-[:HAS_PRICE]->(Price)
--   (Stock)-[:HAS_PRICE]->(Price)
--   (User)-[:WATCHES {added_at}]->(ETF)
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

-- ETFs (전체 ETF 코드/이름 - 포트폴리오 비유니버스 ETF 이름 조회용)
-- 상세 메타데이터(net_assets, expense_ratio, issuer 등)는 AGE ETF 노드에서 관리
CREATE TABLE IF NOT EXISTS etfs (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Portfolios (사용자 포트폴리오)
CREATE TABLE IF NOT EXISTS portfolios (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL DEFAULT 'My Portfolio',
    calculation_base VARCHAR(20) NOT NULL DEFAULT 'CURRENT_TOTAL',
    target_total_amount DECIMAL(15, 2),
    display_order INTEGER NOT NULL DEFAULT 0,
    is_shared BOOLEAN NOT NULL DEFAULT FALSE,
    share_token UUID UNIQUE DEFAULT NULL,
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
    quantity TEXT NOT NULL DEFAULT '0',
    avg_price TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(portfolio_id, ticker)
);

-- Portfolio Snapshots (포트폴리오 일별 스냅샷)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    total_value TEXT NOT NULL,
    prev_value TEXT,
    change_amount TEXT,
    change_rate TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_portfolio_snapshot_date UNIQUE (portfolio_id, date)
);

-- Collection Runs (수집 완료 기록)
CREATE TABLE IF NOT EXISTS collection_runs (
    id SERIAL PRIMARY KEY,
    collected_at DATE NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS last_notification_checked_at TIMESTAMP;

-- Ticker Prices (실시간 현재가 캐시 - 티커별 하루 1건)
CREATE TABLE IF NOT EXISTS ticker_prices (
    ticker     VARCHAR(20)    NOT NULL,
    date       DATE           NOT NULL,
    price      NUMERIC(18, 2) NOT NULL,
    updated_at TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_portfolios_user_id ON portfolios(user_id);
CREATE INDEX IF NOT EXISTS idx_target_allocations_portfolio_id ON target_allocations(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_holdings_portfolio_id ON holdings(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_portfolio_id ON portfolio_snapshots(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_date ON portfolio_snapshots(date);
CREATE INDEX IF NOT EXISTS idx_ticker_prices_date ON ticker_prices(date);

-- Roles (역할 관리)
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO roles (name, description) VALUES
    ('admin', '관리자'), ('member', '일반 회원')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS user_roles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, role_id)
);
CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO postgres;
