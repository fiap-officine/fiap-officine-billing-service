from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.infrastructure.database import Base


class OutboxMessage(Base):
    """Transactional Outbox: mensagem gravada na mesma transação da mudança de
    estado e publicada no SQS de forma assíncrona pelo relay."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    destination: Mapped[str] = mapped_column(String(60), nullable=False)
    message_type: Mapped[str] = mapped_column(String(60), nullable=False)
    envelope: Mapped[dict] = mapped_column(JSON, nullable=False)
    # pending | sent
    status: Mapped[str] = mapped_column(
        String(10), default="pending", nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ProcessedMessage(Base):
    """Registro de mensagens já consumidas (idempotência: SQS é at-least-once)."""

    __tablename__ = "processed_messages"

    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message_type: Mapped[str] = mapped_column(String(60), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
