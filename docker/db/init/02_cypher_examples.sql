-- Few-shot Cypher example store (pgvector)
CREATE TABLE IF NOT EXISTS cypher_examples (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    cypher TEXT NOT NULL,
    description TEXT,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cypher_examples_embedding
    ON cypher_examples USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
