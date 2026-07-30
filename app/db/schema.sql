-- llm-postgres 스키마 (§6). 앱 기동 시 idempotent하게 적용.
-- TODO(2주차): alembic 마이그레이션으로 전환

CREATE EXTENSION IF NOT EXISTS vector;

-- 비동기 잡 (ADR-4)
CREATE TABLE IF NOT EXISTS jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 백엔드가 발급한 jobId (pull 모델) — 형식(UUID 여부) 미확정이라 TEXT 별도 컬럼으로
    -- 매핑. 콜백은 이 값을 echo하고, 백엔드 폴링 조회(GET /v1/jobs/{id})도 이 값 허용.
    external_job_id TEXT,
    expense_id   BIGINT,
    team_id      BIGINT NOT NULL,
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
-- 기존 DB에도 idempotent 적용 (CREATE TABLE IF NOT EXISTS는 기존 테이블에 컬럼을 안 더함)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS external_job_id TEXT;
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'jobs'
          AND column_name = 'team_id') = 'text' THEN
        IF EXISTS (
            SELECT 1 FROM jobs
            WHERE team_id !~ '^[1-9][0-9]*$'
               OR (expense_id IS NOT NULL AND expense_id !~ '^[1-9][0-9]*$')
        ) THEN
            RAISE EXCEPTION
                'jobs의 기존 문자열 ID를 BIGINT로 변환할 수 없습니다. 비숫자 목 데이터를 정리하세요.';
        END IF;
        ALTER TABLE jobs
            ALTER COLUMN expense_id TYPE BIGINT USING expense_id::BIGINT,
            ALTER COLUMN team_id TYPE BIGINT USING team_id::BIGINT;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_external_id ON jobs (external_job_id)
    WHERE external_job_id IS NOT NULL;
-- 같은 지출의 활성(대기·실행 중) 심사 잡은 1개만 — 동시 중복 제출 방지 (§8 멱등성).
-- 완료(succeeded/failed/dead)된 뒤의 재제출은 막지 않는다 (재심사 허용).
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_active_review
    ON jobs (expense_id)
    WHERE type = 'review' AND status IN ('queued', 'running') AND expense_id IS NOT NULL;

-- 회칙·정책 임베딩 (REQ-041)
CREATE TABLE IF NOT EXISTS context_chunks (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id    BIGINT NOT NULL,
    doc_type   TEXT NOT NULL,                      -- rule | policy | category
    version    INT  NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding  vector(1536),
    active     BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'context_chunks'
          AND column_name = 'team_id') = 'text' THEN
        IF EXISTS (SELECT 1 FROM context_chunks WHERE team_id !~ '^[1-9][0-9]*$') THEN
            RAISE EXCEPTION
                'context_chunks의 기존 문자열 team_id를 BIGINT로 변환할 수 없습니다.';
        END IF;
        ALTER TABLE context_chunks
            ALTER COLUMN team_id TYPE BIGINT USING team_id::BIGINT;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_chunks_team_active ON context_chunks (team_id) WHERE active;

-- 판례 (REQ-042)
CREATE TABLE IF NOT EXISTS precedents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         BIGINT NOT NULL,
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
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'precedents'
          AND column_name = 'team_id') = 'text' THEN
        IF EXISTS (SELECT 1 FROM precedents WHERE team_id !~ '^[1-9][0-9]*$') THEN
            RAISE EXCEPTION
                'precedents의 기존 문자열 team_id를 BIGINT로 변환할 수 없습니다.';
        END IF;
        ALTER TABLE precedents
            ALTER COLUMN team_id TYPE BIGINT USING team_id::BIGINT;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_precedents_team_active ON precedents (team_id) WHERE active;

-- 제안 (§6, C2) — BudgetPlanner·PolicyDrafter 개정 모드 산출물. 상태 전이: proposed → accepted | dismissed
CREATE TABLE IF NOT EXISTS proposals (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id    BIGINT NOT NULL,
    type       TEXT NOT NULL,                    -- budget | rule_amendment
    payload    JSONB NOT NULL,
    status     TEXT NOT NULL DEFAULT 'proposed', -- proposed | accepted | dismissed
    decided_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ
);
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'proposals'
          AND column_name = 'team_id') = 'text' THEN
        IF EXISTS (SELECT 1 FROM proposals WHERE team_id !~ '^[1-9][0-9]*$') THEN
            RAISE EXCEPTION
                'proposals의 기존 문자열 team_id를 BIGINT로 변환할 수 없습니다.';
        END IF;
        ALTER TABLE proposals
            ALTER COLUMN team_id TYPE BIGINT USING team_id::BIGINT;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_proposals_team_status ON proposals (team_id, status);

-- HNSW 인덱스는 데이터가 쌓인 뒤 생성 (2주차):
-- CREATE INDEX ON context_chunks USING hnsw (embedding vector_cosine_ops);
-- CREATE INDEX ON precedents USING hnsw (embedding vector_cosine_ops);
