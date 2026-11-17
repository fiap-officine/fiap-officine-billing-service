"""Schema inicial do billing_db: orçamentos, itens, pagamentos, outbox e
idempotência.

Revision ID: 001
Revises:
Create Date: 2026-11-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "orcamentos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("os_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("saga_id", sa.String(36), nullable=True),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("cliente_nome", sa.String(255), nullable=True),
        sa.Column("cliente_email", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("valor_total", sa.Numeric(10, 2), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("motivo", sa.String(500), nullable=True),
        sa.Column("decidido_em", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_orcamentos_cliente_id", "orcamentos", ["cliente_id"])
    op.create_index("ix_orcamentos_status", "orcamentos", ["status"])

    op.create_table(
        "orcamento_itens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("orcamento_id", sa.Integer(), sa.ForeignKey("orcamentos.id"), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False),
        sa.Column("descricao", sa.String(255), nullable=True),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("valor_unitario", sa.Numeric(10, 2), nullable=False),
        sa.Column("valor_total", sa.Numeric(10, 2), nullable=False),
    )
    op.create_index("ix_orcamento_itens_orcamento_id", "orcamento_itens", ["orcamento_id"])

    op.create_table(
        "pagamentos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("orcamento_id", sa.Integer(), sa.ForeignKey("orcamentos.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("valor", sa.Numeric(10, 2), nullable=False),
        sa.Column("metodo", sa.String(50), nullable=True),
        sa.Column("gateway", sa.String(20), nullable=False),
        sa.Column("mp_preference_id", sa.String(100), nullable=True),
        sa.Column("mp_payment_id", sa.String(50), nullable=True),
        sa.Column("mp_refund_id", sa.String(50), nullable=True),
        sa.Column("checkout_url", sa.String(1000), nullable=True),
        sa.Column("status_detail", sa.String(100), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_pagamentos_orcamento_id", "pagamentos", ["orcamento_id"])
    op.create_index("ix_pagamentos_status", "pagamentos", ["status"])
    op.create_index("ix_pagamentos_mp_payment_id", "pagamentos", ["mp_payment_id"])

    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.String(36), nullable=False, unique=True),
        sa.Column("destination", sa.String(60), nullable=False),
        sa.Column("message_type", sa.String(60), nullable=False),
        sa.Column("envelope", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_status", "outbox", ["status"])

    op.create_table(
        "processed_messages",
        sa.Column("message_id", sa.String(36), primary_key=True),
        sa.Column("message_type", sa.String(60), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("processed_messages")
    op.drop_index("ix_outbox_status", table_name="outbox")
    op.drop_table("outbox")
    op.drop_table("pagamentos")
    op.drop_table("orcamento_itens")
    op.drop_table("orcamentos")
