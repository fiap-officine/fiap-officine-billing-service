from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.domain.enums import StatusOrcamento, StatusPagamento
from app.infrastructure.database import Base


def _enum(enum_cls, name: str):
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda cls: [e.value for e in cls],
        native_enum=False,
        length=20,
    )


class Orcamento(Base):
    __tablename__ = "orcamentos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    os_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    saga_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cliente_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    cliente_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cliente_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[StatusOrcamento] = mapped_column(
        _enum(StatusOrcamento, "status_orcamento"),
        nullable=False,
        default=StatusOrcamento.GERADO,
        index=True,
    )
    valor_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    motivo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decidido_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    itens: Mapped[list["OrcamentoItem"]] = relationship(
        "OrcamentoItem",
        back_populates="orcamento",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="OrcamentoItem.id",
    )
    pagamentos: Mapped[list["Pagamento"]] = relationship(
        "Pagamento",
        back_populates="orcamento",
        lazy="selectin",
        order_by="Pagamento.id",
    )


class OrcamentoItem(Base):
    __tablename__ = "orcamento_itens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    orcamento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orcamentos.id"), nullable=False, index=True
    )
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)
    ref_id: Mapped[int] = mapped_column(Integer, nullable=False)
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantidade: Mapped[int] = mapped_column(Integer, nullable=False)
    valor_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    valor_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    orcamento: Mapped["Orcamento"] = relationship("Orcamento", back_populates="itens")


class Pagamento(Base):
    __tablename__ = "pagamentos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    orcamento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orcamentos.id"), nullable=False, index=True
    )
    status: Mapped[StatusPagamento] = mapped_column(
        _enum(StatusPagamento, "status_pagamento"),
        nullable=False,
        default=StatusPagamento.PENDENTE,
        index=True,
    )
    valor: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    metodo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gateway: Mapped[str] = mapped_column(String(20), nullable=False)
    mp_preference_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mp_payment_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True
    )
    mp_refund_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status_detail: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    orcamento: Mapped["Orcamento"] = relationship(
        "Orcamento", back_populates="pagamentos"
    )
