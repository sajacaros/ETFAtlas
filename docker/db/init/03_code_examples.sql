-- Multi-step Python code example store (pgvector)
CREATE TABLE IF NOT EXISTS code_examples (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    question_generalized TEXT,
    code TEXT NOT NULL,
    description TEXT,
    embedding vector(1536),
    status VARCHAR(20) DEFAULT 'active',
    created_by INTEGER REFERENCES users(id),
    source_chat_log_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_code_examples_embedding
    ON code_examples USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
