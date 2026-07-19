-- llm-postgres 스키마 (§6). 앱 기동 시 idempotent하게 적용.
-- TODO(2주차): alembic 마이그레이션으로 전환

CREATE EXTENSION IF NOT EXISTS vector;

-- 비동기 잡 (ADR-4)
CREATE TABLE IF NOT EXISTS jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    expense_id   TEXT,
    team_id      TEXT NOT NULL,
    type         TEXT NOT NULL DEFAULT 'review',   -- review | context_refresh | report | briefing | digest | proposal_budget | proposal_rule_amendment
    status       TEXT NOT NULL DEFAULT 'queued',   -- queued | running | succeeded | failed | dead
    attempts     INT  NOT NULL DEFAULT 0,
    max_attempts INT  NOT NULL DEFAULT 3,
    payload      JSONB NOT NULL,
    result       JSONB,
    cost_usd     NUMERIC(10, 5) DEFAULT 0,
    tokens_in    INT DEFAULT 0,
    tokens_out   INT DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status, created_at);
-- 같은 지출의 활성(대기·실행 중) 심사 잡은 1개만 — 동시 중복 제출 방지 (§8 멱등성).
-- 완료(succeeded/failed/dead)된 뒤의 재제출은 막지 않는다 (재심사 허용).
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_active_review
    ON jobs (expense_id)
    WHERE type = 'review' AND status IN ('queued', 'running') AND expense_id IS NOT NULL;

-- 회칙·정책 임베딩 (REQ-041)
CREATE TABLE IF NOT EXISTS context_chunks (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id    TEXT NOT NULL,
    doc_type   TEXT NOT NULL,                      -- rule | policy | category
    version    INT  NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding  vector(1536),
    active     BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_team_active ON context_chunks (team_id) WHERE active;

-- 판례 (REQ-042)
CREATE TABLE IF NOT EXISTS precedents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         TEXT NOT NULL,
    expense_summary TEXT NOT NULL,                 -- 익명화된 요약
    decision        TEXT NOT NULL,                 -- approve | reject | escalate
    decided_by      TEXT NOT NULL,                 -- AGENT | ADMIN
    reason          TEXT,
    is_override     BOOLEAN NOT NULL DEFAULT false,
    confidence      REAL,
    rule_version    INT,
    model_version   TEXT,
    prompt_version  TEXT,
    embedding       vector(1536),
    active          BOOLEAN NOT NULL DEFAULT true, -- 삭제 대신 비활성화
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_precedents_team_active ON precedents (team_id) WHERE active;

-- 제안 (§6, C2) — BudgetPlanner·PolicyDrafter 개정 모드 산출물. 상태 전이: proposed → accepted | dismissed
CREATE TABLE IF NOT EXISTS proposals (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id    TEXT NOT NULL,
    type       TEXT NOT NULL,                    -- budget | rule_amendment
    payload    JSONB NOT NULL,
    status     TEXT NOT NULL DEFAULT 'proposed', -- proposed | accepted | dismissed
    decided_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_proposals_team_status ON proposals (team_id, status);

-- HNSW 인덱스는 데이터가 쌓인 뒤 생성 (2주차):
-- CREATE INDEX ON context_chunks USING hnsw (embedding vector_cosine_ops);
-- CREATE INDEX ON precedents USING hnsw (embedding vector_cosine_ops);
