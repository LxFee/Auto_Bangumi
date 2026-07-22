"""Persistent domain state for the episode naming workbench.

The stable seams are deliberately separate from the legacy ``Bangumi`` row:
groups own work metadata, plans own per-downloader-file identity, and revisions
own approved rename intent.  Existing downloader tags can therefore continue
to refer to rule ids while the workbench aggregates rules by group.
"""

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BangumiGroup(SQLModel, table=True):
    __tablename__ = "bangumi_group"
    __table_args__ = (
        CheckConstraint(
            "episode_type IN ('episode', 'movie', 'special')",
            name="ck_bangumi_group_episode_type",
        ),
        Index(
            "ux_bangumi_group_migration_key",
            "migration_key",
            unique=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    official_title: str
    year: str | None = None
    season: int = 1
    episode_type: str = Field(default="episode", max_length=32)
    poster_link: str | None = None
    air_weekday: int | None = None
    migration_review: bool = False
    migration_review_reason: str | None = None
    migration_key: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BangumiGroupMember(SQLModel, table=True):
    __tablename__ = "bangumi_group_member"
    __table_args__ = (Index("ix_bangumi_group_member_group_id", "group_id"),)

    rule_id: int = Field(primary_key=True, foreign_key="bangumi.id")
    group_id: int = Field(foreign_key="bangumi_group.id")
    created_at: datetime = Field(default_factory=utc_now)


class NamingPlan(SQLModel, table=True):
    """Stable state for one downloader file.

    ``downloader_type + task_id + file_index`` is the media file identity.
    Paths and parsed fields are observations that may change over time.
    """

    __tablename__ = "naming_plan"
    __table_args__ = (
        CheckConstraint(
            "file_kind IN ('video', 'subtitle')",
            name="ck_naming_plan_file_kind",
        ),
        CheckConstraint(
            "origin IN ('new', 'legacy')",
            name="ck_naming_plan_origin",
        ),
        CheckConstraint(
            "discovery_state IN ('active', 'missing')",
            name="ck_naming_plan_discovery_state",
        ),
        Index(
            "ux_naming_plan_file_identity",
            "downloader_type",
            "task_id",
            "file_index",
            unique=True,
        ),
        Index("ix_naming_plan_group_id", "group_id"),
        Index("ix_naming_plan_rule_id", "rule_id"),
        Index("ix_naming_plan_subtitle_of_id", "subtitle_of_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="bangumi_group.id")
    rule_id: int = Field(foreign_key="bangumi.id")
    downloader_type: str = Field(max_length=32)
    task_id: str
    file_index: int
    file_kind: str = Field(max_length=16)
    subtitle_of_id: int | None = Field(default=None, foreign_key="naming_plan.id")
    baseline_path: str
    current_path: str
    default_snapshot: str = "{}"
    manual_fields: str | None = None
    required_fields: str = "[]"
    target_path: str | None = None
    anomaly_reason: str | None = None
    origin: str = Field(default="new", max_length=16)
    discovery_state: str = Field(default="active", max_length=16)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class NamingPlanRevision(SQLModel, table=True):
    __tablename__ = "naming_plan_revision"
    __table_args__ = (
        CheckConstraint(
            "state IN ('draft', 'approved', 'running', 'retry', 'blocked', "
            "'applied', 'superseded')",
            name="ck_naming_plan_revision_state",
        ),
        Index(
            "ux_naming_plan_revision_number",
            "plan_id",
            "revision",
            unique=True,
        ),
        Index("ix_naming_plan_revision_state", "state"),
    )

    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="naming_plan.id")
    revision: int
    state: str = Field(default="draft", max_length=16)
    field_snapshot: str = "{}"
    target_manifest: str = "[]"
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    approved_at: datetime | None = None
    applied_at: datetime | None = None


class NamingExecution(SQLModel, table=True):
    """Lease and fencing state for one video-led naming unit."""

    __tablename__ = "naming_execution"
    __table_args__ = (
        CheckConstraint(
            "state IN ('idle', 'pending', 'running', 'retry', 'blocked', 'done')",
            name="ck_naming_execution_state",
        ),
        CheckConstraint(
            "fence_token >= 0",
            name="ck_naming_execution_fence_token",
        ),
        Index("ix_naming_execution_state_retry_at", "state", "retry_at"),
    )

    plan_id: int = Field(primary_key=True, foreign_key="naming_plan.id")
    approved_revision_id: int | None = Field(
        default=None, foreign_key="naming_plan_revision.id"
    )
    applied_revision_id: int | None = Field(
        default=None, foreign_key="naming_plan_revision.id"
    )
    state: str = Field(default="idle", max_length=16)
    fence_token: int = 0
    lease_owner: str | None = Field(default=None, max_length=64)
    lease_expires_at: datetime | None = None
    retry_at: datetime | None = None
    last_error: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)
