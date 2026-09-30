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
