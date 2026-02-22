-- ============================================================
-- 역할 관리 AGE → RDB 마이그레이션
-- 실행: docker exec -i etf-atlas-db psql -U postgres -d etf_atlas < docker/db/migrate_roles_to_rdb.sql
-- ============================================================

BEGIN;

-- 1) RDB 테이블 생성 + 시딩
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

-- 2) AGE admin 유저 → RDB user_roles 마이그레이션
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- AGE에서 admin role을 가진 user_id 추출 → 임시 테이블
CREATE TEMP TABLE _age_admins (user_id INTEGER);

INSERT INTO _age_admins (user_id)
SELECT (result::json->>'user_id')::INTEGER
FROM cypher('etf_graph', $$
    MATCH (u:User)
    WHERE u.role = 'admin'
    RETURN {user_id: u.user_id}
$$) AS (result agtype);

-- admin 역할 할당
INSERT INTO user_roles (user_id, role_id)
SELECT a.user_id, r.id
FROM _age_admins a, roles r
WHERE r.name = 'admin'
  AND EXISTS (SELECT 1 FROM users u WHERE u.id = a.user_id)
ON CONFLICT (user_id, role_id) DO NOTHING;

-- 나머지 유저는 member 역할 할당
INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id
FROM users u, roles r
WHERE r.name = 'member'
  AND u.id NOT IN (SELECT user_id FROM user_roles)
ON CONFLICT (user_id, role_id) DO NOTHING;

DROP TABLE _age_admins;

-- 3) AGE User 노드에서 role 속성 제거
SELECT * FROM cypher('etf_graph', $$
    MATCH (u:User)
    WHERE u.role IS NOT NULL
    SET u.role = null
    RETURN {user_id: u.user_id}
$$) AS (result agtype);

-- 4) search_path 복원
SET search_path = public;

COMMIT;

-- 5) 결과 확인
SELECT r.name AS role, count(*) AS user_count
FROM user_roles ur
JOIN roles r ON r.id = ur.role_id
GROUP BY r.name;
