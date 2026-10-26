-- ==============================================================================
-- Enterprise RAG & Tabular Execution Harness - Database Schema (PostgreSQL 16)
-- Clean Architecture DDL with RBAC, Ingestion, Catalog, and Audit Tracking
-- ==============================================================================

-- Enable UUID extension if available
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Departments
CREATE TABLE IF NOT EXISTS departments (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Users
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    username VARCHAR(128) NOT NULL UNIQUE,
    email VARCHAR(255),
    full_name VARCHAR(255),
    department_id VARCHAR(64) REFERENCES departments(id) ON DELETE SET NULL,
    role VARCHAR(64) NOT NULL DEFAULT 'user', -- 'admin', 'analyst', 'user'
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Files (Uploaded assets with SHA-256 deduplication and RBAC metadata)
CREATE TABLE IF NOT EXISTS files (
    id VARCHAR(64) PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(32) NOT NULL, -- 'xlsx', 'csv', 'pdf', 'docx', 'md', 'txt'
    file_size_bytes BIGINT NOT NULL,
    sha256_hash VARCHAR(64) NOT NULL,
    storage_path VARCHAR(512) NOT NULL,
    owner_user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    department_id VARCHAR(64) NOT NULL REFERENCES departments(id),
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_files_department_rbac ON files(department_id, is_public, owner_user_id);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256_hash);

-- 4. Ingestion Jobs (Zero-dependency stateful queue)
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id VARCHAR(64) PRIMARY KEY,
    file_id VARCHAR(64) NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    job_type VARCHAR(32) NOT NULL, -- 'tabular', 'document'
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'PROCESSING', 'COMPLETED', 'FAILED'
    progress_pct INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status ON ingestion_jobs(status, created_at);

-- 5. Tables Catalog (For Tabular data: .xlsx sheets, .csv files)
CREATE TABLE IF NOT EXISTS tables_catalog (
    id VARCHAR(64) PRIMARY KEY,
    file_id VARCHAR(64) NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    sheet_name VARCHAR(255) NOT NULL,
    parquet_path VARCHAR(512) NOT NULL,
    owner_user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    department_id VARCHAR(64) NOT NULL REFERENCES departments(id),
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    row_count BIGINT NOT NULL DEFAULT 0,
    table_description TEXT,
    business_keywords JSONB DEFAULT '[]'::jsonb,
    warnings JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tables_catalog_rbac ON tables_catalog(department_id, is_public, owner_user_id);
CREATE INDEX IF NOT EXISTS idx_tables_catalog_file_id ON tables_catalog(file_id);

-- 6. Columns Catalog (Granular schema per table)
CREATE TABLE IF NOT EXISTS columns_catalog (
    id VARCHAR(64) PRIMARY KEY,
    table_id VARCHAR(64) NOT NULL REFERENCES tables_catalog(id) ON DELETE CASCADE,
    original_name VARCHAR(255) NOT NULL,
    column_alias VARCHAR(255) NOT NULL,
    data_type VARCHAR(64) NOT NULL,
    sample_values JSONB DEFAULT '[]'::jsonb,
    min_val TEXT,
    max_val TEXT,
    null_ratio DOUBLE PRECISION DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_columns_catalog_table_id ON columns_catalog(table_id);

-- 7. Column Distinct Values (For Entity Linking)
CREATE TABLE IF NOT EXISTS column_values (
    id VARCHAR(64) PRIMARY KEY,
    table_id VARCHAR(64) NOT NULL REFERENCES tables_catalog(id) ON DELETE CASCADE,
    column_name VARCHAR(255) NOT NULL,
    original_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    frequency INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_column_values_lookup ON column_values(table_id, column_name, normalized_value);

-- 8. Entity Aliases (Pre-seeded & Admin-managed dictionary)
CREATE TABLE IF NOT EXISTS entity_aliases (
    id VARCHAR(64) PRIMARY KEY,
    standard_name VARCHAR(255) NOT NULL,
    alias VARCHAR(255) NOT NULL,
    entity_type VARCHAR(64) NOT NULL DEFAULT 'custom', -- 'location', 'department', 'quarter', 'metric'
    department_id VARCHAR(64) REFERENCES departments(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_entity_aliases_alias ON entity_aliases(alias);

-- Seed initial Vietnamese entity aliases
INSERT INTO entity_aliases (id, standard_name, alias, entity_type) VALUES
    ('alias-hn', 'Hà Nội', 'hn', 'location'),
    ('alias-hcm', 'Hồ Chí Minh', 'hcm', 'location'),
    ('alias-tphcm', 'Hồ Chí Minh', 'tphcm', 'location'),
    ('alias-sg', 'Hồ Chí Minh', 'sg', 'location'),
    ('alias-dn', 'Đà Nẵng', 'dn', 'location'),
    ('alias-hp', 'Hải Phòng', 'hp', 'location'),
    ('alias-ct', 'Cần Thơ', 'ct', 'location'),
    ('alias-q1', 'Quý 1', 'q1', 'quarter'),
    ('alias-q2', 'Quý 2', 'q2', 'quarter'),
    ('alias-q3', 'Quý 3', 'q3', 'quarter'),
    ('alias-q4', 'Quý 4', 'q4', 'quarter')
ON CONFLICT (id) DO NOTHING;

-- 9. Few-shot Examples (Synthetic generated & User verified)
CREATE TABLE IF NOT EXISTS fewshot_examples (
    id VARCHAR(64) PRIMARY KEY,
    table_id VARCHAR(64) NOT NULL REFERENCES tables_catalog(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    sql_query TEXT NOT NULL,
    language VARCHAR(32) NOT NULL DEFAULT 'sql',
    source VARCHAR(32) NOT NULL DEFAULT 'synthetic', -- 'synthetic', 'verified'
    difficulty VARCHAR(32) NOT NULL DEFAULT 'medium',
    embedding JSONB, -- Stored question embedding for similarity retrieval
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fewshot_table_source ON fewshot_examples(table_id, source, is_active);

-- 10. Documents (Metadata for text / scan documents: PDF, DOCX, MD, TXT)
CREATE TABLE IF NOT EXISTS documents (
    id VARCHAR(64) PRIMARY KEY,
    file_id VARCHAR(64) NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    doc_metadata JSONB DEFAULT '{}'::jsonb,
    total_pages INTEGER NOT NULL DEFAULT 1,
    total_chunks INTEGER NOT NULL DEFAULT 0,
    owner_user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    department_id VARCHAR(64) NOT NULL REFERENCES departments(id),
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_rbac ON documents(department_id, is_public, owner_user_id);
CREATE INDEX IF NOT EXISTS idx_documents_file_id ON documents(file_id);

-- 11. Chat Sessions (Multi-turn conversational threads)
CREATE TABLE IF NOT EXISTS chat_sessions (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    title VARCHAR(255) NOT NULL DEFAULT 'Cuộc trò chuyện mới',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id, updated_at);

-- 12. Chat Messages (Turn history, rewritten queries, and latency tracking)
CREATE TABLE IF NOT EXISTS chat_messages (
    id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL, -- 'user', 'assistant', 'system'
    rewritten_query TEXT,
    route VARCHAR(32), -- 'TABULAR', 'DOCUMENT', 'HYBRID', 'CLARIFY', 'CHITCHAT', 'OUT_OF_SCOPE'
    content TEXT NOT NULL,
    structured_response JSONB,
    latency_ms INTEGER DEFAULT 0,
    feedback VARCHAR(32), -- 'like', 'dislike'
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at);

-- 13. Audit Logs (Enterprise audit tracking for every action)
CREATE TABLE IF NOT EXISTS audit_logs (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    department_id VARCHAR(64),
    action VARCHAR(64) NOT NULL, -- 'UPLOAD', 'QUERY', 'EXEC_SQL', 'EXEC_PANDAS', 'DELETE'
    details JSONB DEFAULT '{}'::jsonb,
    ip_address VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'SUCCESS', -- 'SUCCESS', 'FAILED'
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_user_action ON audit_logs(user_id, action, created_at);
