"""SQLModel table definitions for all DeathStar database tables."""

# NOTE: Do NOT use `from __future__ import annotations` here.
# SQLAlchemy/SQLModel need runtime type evaluation for Relationship() to work.

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, ForeignKey, Index, String, Text
from sqlmodel import Field, Relationship, SQLModel


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Conversations + Messages
# ---------------------------------------------------------------------------


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("idx_conversations_repo", "repo"),
        Index("idx_conversations_updated", "updated_at"),
        Index("idx_conversations_repo_branch", "repo", "branch"),
    )

    id: str = Field(primary_key=True)
    repo: str = Field(nullable=False)
    title: str = Field(nullable=False)
    created_at: str = Field(nullable=False, default_factory=_utcnow)
    updated_at: str = Field(nullable=False, default_factory=_utcnow)
    sdk_session_id: Optional[str] = Field(default=None)
    branch: Optional[str] = Field(default=None)

    messages: list["Message"] = Relationship(
        back_populates="conversation",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    conversation_branches: list["ConversationBranch"] = Relationship(
        back_populates="conversation",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class ConversationBranch(SQLModel, table=True):
    """Many-to-many link between conversations and branches they've been used on."""

    __tablename__ = "conversation_branches"
    __table_args__ = (
        Index("idx_conversation_branches_conv", "conversation_id"),
    )

    conversation_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    branch: str = Field(primary_key=True)
    added_at: str = Field(nullable=False, default_factory=_utcnow)

    conversation: Optional[Conversation] = Relationship(
        back_populates="conversation_branches",
    )


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_conversation", "conversation_id", "timestamp"),
    )

    id: str = Field(primary_key=True)
    conversation_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    role: str = Field(nullable=False)
    content: str = Field(sa_column=Column(Text, nullable=False))
    timestamp: str = Field(nullable=False)
    workflow: Optional[str] = Field(default=None)
    provider: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)
    duration_ms: Optional[int] = Field(default=None)
    input_tokens: Optional[int] = Field(default=None)
    output_tokens: Optional[int] = Field(default=None)
    agent_blocks: Optional[str] = Field(default=None, sa_column=Column(Text))

    conversation: Optional[Conversation] = Relationship(back_populates="messages")


# ---------------------------------------------------------------------------
# Memory Bank
# ---------------------------------------------------------------------------


class Memory(SQLModel, table=True):
    __tablename__ = "memories"
    __table_args__ = (
        Index("idx_memories_repo", "repo", "created_at"),
    )

    id: str = Field(primary_key=True)
    repo: str = Field(nullable=False)
    content: str = Field(sa_column=Column(Text, nullable=False))
    source_message_id: str = Field(default="")
    source_prompt: str = Field(default="")
    tags: str = Field(default="[]")
    created_at: str = Field(nullable=False, default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


class Feedback(SQLModel, table=True):
    __tablename__ = "feedback"
    __table_args__ = (
        Index("idx_feedback_repo", "repo", "created_at"),
        Index("idx_feedback_message", "message_id"),
    )

    id: str = Field(primary_key=True)
    message_id: str = Field(nullable=False)
    conversation_id: Optional[str] = Field(default=None)
    kind: str = Field(nullable=False)
    repo: str = Field(nullable=False)
    content: str = Field(default="", sa_column=Column(Text, default=""))
    prompt: str = Field(default="", sa_column=Column(Text, default=""))
    comment: str = Field(default="")
    created_at: str = Field(nullable=False, default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Usage Log
# ---------------------------------------------------------------------------


class UsageLog(SQLModel, table=True):
    __tablename__ = "usage_log"
    __table_args__ = (
        Index("idx_usage_repo", "repo", "created_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: Optional[str] = Field(default=None)
    message_id: Optional[str] = Field(default=None)
    repo: str = Field(nullable=False)
    workflow: str = Field(nullable=False)
    provider: str = Field(nullable=False)
    model: str = Field(nullable=False)
    duration_ms: int = Field(nullable=False)
    input_tokens: Optional[int] = Field(default=None)
    output_tokens: Optional[int] = Field(default=None)
    persona: Optional[str] = Field(default=None)
    created_at: str = Field(nullable=False, default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Message Queue
# ---------------------------------------------------------------------------


class MessageQueue(SQLModel, table=True):
    __tablename__ = "message_queue"
    __table_args__ = (
        Index("idx_queue_status", "status", "created_at"),
        Index("idx_queue_conversation", "conversation_id", "status"),
    )

    id: str = Field(primary_key=True)
    conversation_id: str = Field(nullable=False)
    repo: str = Field(nullable=False)
    branch: Optional[str] = Field(default=None)
    message: str = Field(sa_column=Column(Text, nullable=False))
    workflow: str = Field(nullable=False, default="prompt")
    model: Optional[str] = Field(default=None)
    system_prompt: Optional[str] = Field(default=None, sa_column=Column(Text))
    status: str = Field(nullable=False, default="pending")
    result_message_id: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    created_at: str = Field(nullable=False, default_factory=_utcnow)
    started_at: Optional[str] = Field(default=None)
    completed_at: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class Document(SQLModel, table=True):
    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_repo", "repo", "updated_at"),
    )

    id: str = Field(primary_key=True)
    repo: str = Field(nullable=False)
    title: str = Field(nullable=False)
    content: str = Field(sa_column=Column(Text, nullable=False))
    document_type: str = Field(nullable=False, default="tech_spec")
    source_conversation_id: Optional[str] = Field(default=None)
    created_at: str = Field(nullable=False, default_factory=_utcnow)
    updated_at: str = Field(nullable=False, default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Branch PRs (cached GitHub PR state)
# ---------------------------------------------------------------------------


class BranchPR(SQLModel, table=True):
    __tablename__ = "branch_prs"
    __table_args__ = (
        # No UniqueConstraint needed — (repo, branch) is already the composite PK.
        Index("idx_branch_prs_repo", "repo"),
    )

    repo: str = Field(primary_key=True)
    branch: str = Field(primary_key=True)
    pr_number: int = Field(nullable=False)
    pr_url: str = Field(nullable=False)
    pr_title: str = Field(nullable=False)
    pr_state: str = Field(nullable=False, default="open")
    draft: bool = Field(nullable=False, default=False)
    user: str = Field(nullable=False, default="")
    base_branch: str = Field(nullable=False, default="main")
    additions: Optional[int] = Field(default=None)
    deletions: Optional[int] = Field(default=None)
    changed_files: Optional[int] = Field(default=None)
    mergeable: Optional[bool] = Field(default=None)
    mergeable_state: Optional[str] = Field(default=None)
    updated_at: str = Field(nullable=False, default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Preview Deployments
# ---------------------------------------------------------------------------


class PreviewDeployment(SQLModel, table=True):
    __tablename__ = "preview_deployments"
    __table_args__ = (
        Index("idx_preview_repo_branch", "repo", "branch"),
        Index("idx_preview_status", "status"),
    )

    id: str = Field(primary_key=True)
    repo: str = Field(nullable=False)
    branch: str = Field(nullable=False)
    provider: str = Field(nullable=False)  # "render" | "vercel"
    provider_service_id: str = Field(nullable=False)
    status: str = Field(nullable=False, default="pending")
    preview_url: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    created_at: str = Field(nullable=False, default_factory=_utcnow)
    updated_at: str = Field(nullable=False, default_factory=_utcnow)
