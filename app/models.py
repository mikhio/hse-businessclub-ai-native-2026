"""Small relational model; invariants also live in PostgreSQL constraints."""

from datetime import datetime, timezone
import secrets

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    headline: Mapped[str] = mapped_column(String(140), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[str] = mapped_column(String(300), default="")
    password_hash: Mapped[str] = mapped_column(String(256))


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("author_id", "creation_key", name="one_publication_per_request"),
        CheckConstraint("kind IN ('startup', 'vacancy')", name="publication_kind"),
        CheckConstraint("status IN ('open', 'closed')", name="publication_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    creation_key: Mapped[str] = mapped_column(String(80), default=lambda: secrets.token_urlsafe(24))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    looking_for: Mapped[str] = mapped_column(String(300))
    work_format: Mapped[str] = mapped_column(String(80), default="По договорённости")
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("publication_id", "applicant_id", name="one_application_per_person"),
        CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name="application_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"), index=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
