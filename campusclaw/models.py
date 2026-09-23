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
