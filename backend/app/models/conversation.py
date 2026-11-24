from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Conversation(Base):
    """A chat thread owned by exactly one user.

    Messages reuse ``QueryLog`` rows (question + answer + citations), so chat
    history, analytics and observability keep a single source of truth instead
    of a second message table.
    """

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = Column(String(200), nullable=False, default="New chat")
    is_pinned = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    messages = relationship(
        "QueryLog",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="QueryLog.id",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Conversation id={self.id} user={self.user_id} pinned={self.is_pinned}>"
