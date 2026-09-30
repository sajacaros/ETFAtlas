-- =====================================================
-- Relational Tables (시계열/사용자 데이터)
-- =====================================================

-- Users (ID/비밀번호 로그인)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    last_notification_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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
    snapshot_enabled BOOLEAN NOT NULL DEFAULT FALSE,
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

-- Holdings (실제 보유, quantity/avg_price는 AES-256-GCM 암호문)
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

-- Portfolio Snapshots (포트폴리오 일별 스냅샷, 금액 컬럼은 암호문)
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

-- Ticker Prices (실시간 현재가 캐시 - 티커별 하루 1건)
CREATE TABLE IF NOT EXISTS ticker_prices (
    ticker     VARCHAR(20)    NOT NULL,
    date       DATE           NOT NULL,
    price      NUMERIC(18, 2) NOT NULL,
    updated_at TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

-- KIS Open API 접근 토큰 캐시 (발급 1분 1회 제한, 24h 유효)
CREATE TABLE IF NOT EXISTS kis_tokens (
    app_key_hash VARCHAR(64) PRIMARY KEY,
    access_token TEXT        NOT NULL,
    expires_at   TIMESTAMP   NOT NULL,
    updated_at   TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 개장일 캐시 (KIS 국내휴장일조회는 1일 1회 호출 권장)
CREATE TABLE IF NOT EXISTS market_calendar (
    date       DATE      PRIMARY KEY,
    is_open    BOOLEAN   NOT NULL,
    checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Chat logs (챗봇 피드백 루프)
CREATE TABLE IF NOT EXISTS chat_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    generated_code TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Multi-step Python code example store (pgvector)
CREATE TABLE IF NOT EXISTS code_examples (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    question_generalized TEXT,
    code TEXT NOT NULL,
    description TEXT,
    embedding vector(768),
    status VARCHAR(20) DEFAULT 'active',
    created_by INTEGER REFERENCES users(id),
    source_chat_log_id INTEGER REFERENCES chat_logs(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_portfolios_user_id ON portfolios(user_id);
CREATE INDEX IF NOT EXISTS idx_target_allocations_portfolio_id ON target_allocations(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_holdings_portfolio_id ON holdings(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_portfolio_id ON portfolio_snapshots(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_date ON portfolio_snapshots(date);
CREATE INDEX IF NOT EXISTS idx_ticker_prices_date ON ticker_prices(date);
CREATE INDEX IF NOT EXISTS idx_chat_logs_user_id ON chat_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_logs_status ON chat_logs(status);
CREATE INDEX IF NOT EXISTS idx_code_examples_embedding
    ON code_examples USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
