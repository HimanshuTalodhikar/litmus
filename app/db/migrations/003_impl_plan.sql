-- app/db/migrations/003_impl_plan.sql

ALTER TABLE feature_requests ADD COLUMN IF NOT EXISTS impl_status VARCHAR(20) DEFAULT 'not_started'
    CHECK (impl_status IN ('not_started', 'generating', 'generated', 'failed'));
ALTER TABLE feature_requests ADD COLUMN IF NOT EXISTS impl_plan_path VARCHAR(500);
ALTER TABLE feature_requests ADD COLUMN IF NOT EXISTS impl_error TEXT;
ALTER TABLE feature_requests ALTER COLUMN impl_status SET DEFAULT 'not_started';
