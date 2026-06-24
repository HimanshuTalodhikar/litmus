-- app/db/migrations/002_feature_requests.sql

CREATE TABLE IF NOT EXISTS feature_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fr_number SERIAL UNIQUE,
    workspace_id VARCHAR(100) NOT NULL DEFAULT 'default',

    -- Content
    raw_text TEXT NOT NULL,
    enriched_text TEXT,
    extracted_intent JSONB,

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'requested'
        CHECK (status IN (
            'requested', 'under_review', 'accepted', 'rejected',
            'backlog', 'scheduled', 'in_progress', 'shipped'
        )),

    -- Prioritization
    priority_score NUMERIC(5,2),
    reach_score INTEGER CHECK (reach_score BETWEEN 1 AND 10),
    impact_score INTEGER CHECK (impact_score BETWEEN 1 AND 3),
    confidence_score NUMERIC(3,2),
    effort_estimate VARCHAR(10),

    -- Deduplication
    dedup_status VARCHAR(20) DEFAULT 'pending',
    dedup_match_id UUID REFERENCES feature_requests(id),
    dedup_similarity_score NUMERIC(3,2),

    -- Jira
    jira_issue_key VARCHAR(50),
    jira_issue_url VARCHAR(500),

    -- Context
    requester_id VARCHAR(50),
    slack_channel_id VARCHAR(20),
    slack_thread_ts VARCHAR(30),
    slack_message_ts VARCHAR(30),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    shipped_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_fr_status ON feature_requests(status);
CREATE INDEX IF NOT EXISTS idx_fr_jira ON feature_requests(jira_issue_key);
CREATE INDEX IF NOT EXISTS idx_fr_workspace ON feature_requests(workspace_id);
CREATE INDEX IF NOT EXISTS idx_fr_priority ON feature_requests(priority_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_fr_created ON feature_requests(created_at DESC);

-- Full-text search for dedup
ALTER TABLE feature_requests ADD COLUMN IF NOT EXISTS enriched_text_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(enriched_text, raw_text))) STORED;
CREATE INDEX IF NOT EXISTS idx_fr_fulltext ON feature_requests USING GIN (enriched_text_tsv);
