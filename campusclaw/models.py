from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(db.String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(db.String(255), nullable=False)
    role: Mapped[str] = mapped_column(db.String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    __table_args__ = (CheckConstraint("role IN ('teacher', 'student')"),)


class Class(db.Model):
    __tablename__ = "classes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(100), unique=True, nullable=False)


class ClassMembership(db.Model):
    __tablename__ = "class_memberships"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "class_id"),)


class LoginSession(db.Model):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_digest: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    active_class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    expires_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(db.DateTime)


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"
    key_digest: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    failed_count: Mapped[int] = mapped_column(nullable=False)
    window_start: Mapped[datetime] = mapped_column(db.DateTime, nullable=False)


class Material(db.Model):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    original_name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(db.String(80), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(db.String(20), default="ready", nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_materials_class_status_created", "class_id", "status", "created_at"),)


class KnowledgeDocument(db.Model):
    __tablename__ = "knowledge_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), unique=True, nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    title: Mapped[str] = mapped_column(db.String(255), nullable=False)
    body: Mapped[str] = mapped_column(db.Text, nullable=False, default="")
    stored_name: Mapped[str] = mapped_column(db.String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)


class KnowledgeChunk(db.Model):
    __tablename__ = "knowledge_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False,
    )
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    generation: Mapped[int] = mapped_column(nullable=False, default=1)
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    chunk_text: Mapped[str] = mapped_column(db.Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(nullable=False)
    end_offset: Mapped[int] = mapped_column(nullable=False)
    offset_basis: Mapped[str] = mapped_column(db.String(30), nullable=False, default="original_text")
    index_status: Mapped[str] = mapped_column(db.String(20), nullable=False, default="pending")
    vector_status: Mapped[str] = mapped_column(db.String(20), nullable=False, default="pending")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("knowledge_document_id", "generation", "chunk_index"),
        CheckConstraint("end_offset >= start_offset"),
        CheckConstraint("index_status IN ('pending', 'ready', 'failed')"),
        CheckConstraint("vector_status IN ('pending', 'ready', 'failed', 'disabled')"),
        Index("ix_chunks_class_active_status", "class_id", "is_active", "index_status"),
    )


class PromptTemplate(db.Model):
    __tablename__ = "prompt_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    app_key: Mapped[str] = mapped_column(db.String(40), nullable=False)
    name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    content: Mapped[str] = mapped_column(db.Text, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    __table_args__ = (UniqueConstraint("class_id", "app_key", "name"),)


class Skill(db.Model):
    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    description: Mapped[str] = mapped_column(db.String(500), nullable=False)
    content: Mapped[str] = mapped_column(db.Text, nullable=False)
    tools_json: Mapped[str] = mapped_column(db.Text, nullable=False, default="[]")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    __table_args__ = (UniqueConstraint("class_id", "name"),)


class Conversation(db.Model):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    app_key: Mapped[str] = mapped_column(db.String(40), nullable=False)
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("prompt_templates.id"))
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id"))
    builtin_skill: Mapped[str | None] = mapped_column(db.String(40))
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)


class ConversationMessage(db.Model):
    __tablename__ = "conversation_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(db.String(20), nullable=False)
    content: Mapped[str] = mapped_column(db.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)


class MCPServer(db.Model):
    __tablename__ = "mcp_servers"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    name: Mapped[str] = mapped_column(db.String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(db.String(500), nullable=False)
    auth_token: Mapped[str] = mapped_column(db.String(500), nullable=False)
    connected: Mapped[bool] = mapped_column(default=False, nullable=False)
    tools_json: Mapped[str] = mapped_column(db.Text, nullable=False, default="[]")
    __table_args__ = (UniqueConstraint("class_id", "name"),)


class MCPAudit(db.Model):
    __tablename__ = "mcp_audits"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tool_ref: Mapped[str] = mapped_column(db.String(180), nullable=False)
    status: Mapped[str] = mapped_column(db.String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)
