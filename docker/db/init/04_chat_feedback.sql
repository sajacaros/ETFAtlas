-- Chat feedback loop: chat_logs table + code_examples seeding

CREATE TABLE IF NOT EXISTS chat_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    generated_code TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_logs_user_id ON chat_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_logs_status ON chat_logs(status);

-- Add FK from code_examples.source_chat_log_id -> chat_logs.id
ALTER TABLE code_examples
    ADD CONSTRAINT fk_code_examples_chat_log
    FOREIGN KEY (source_chat_log_id) REFERENCES chat_logs(id);
