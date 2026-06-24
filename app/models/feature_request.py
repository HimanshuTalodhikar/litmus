from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
import enum


class FeatureRequestStatus(str, enum.Enum):
    REQUESTED = "requested"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    BACKLOG = "backlog"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    SHIPPED = "shipped"


class ImplStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"


class FeatureRequest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    fr_number: Optional[int] = None  # Human-readable: FR-001, FR-002

    # Content
    raw_text: str
    enriched_text: Optional[str] = None
    extracted_intent: Optional[dict] = None

    # Status
    status: FeatureRequestStatus = FeatureRequestStatus.REQUESTED

    # Prioritization
    priority_score: Optional[float] = None  # 0-100
    reach_score: Optional[int] = None      # 1-10
    impact_score: Optional[int] = None     # 1-3
    confidence_score: Optional[float] = None  # 0.5-1.0
    effort_estimate: Optional[str] = None  # "xs", "s", "m", "l", "xl"

    # Deduplication
    dedup_status: str = "pending"  # pending / matched / new
    dedup_match_id: Optional[UUID] = None
    dedup_similarity_score: Optional[float] = None

    # Jira
    jira_issue_key: Optional[str] = None
    jira_issue_url: Optional[str] = None

    # Context
    requester_id: Optional[str] = None  # Slack user ID
    slack_channel_id: Optional[str] = None
    slack_thread_ts: Optional[str] = None
    slack_message_ts: Optional[str] = None
    workspace_id: Optional[str] = "default"

    # Implementation plan
    impl_status: ImplStatus = ImplStatus.NOT_STARTED
    impl_plan_path: Optional[str] = None
    impl_error: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    shipped_at: Optional[datetime] = None
