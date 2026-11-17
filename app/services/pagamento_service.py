"""Pagamentos: cobrança no Mercado Pago, processamento de notificações
(webhook / reconciliação) e estorno (compensação)."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.billing import Orcamento, Pagamento
from app.domain.enums import (
    MP_STATUS,
    ORCAMENTO_ENCERRADO,
    StatusOrcamento,
    StatusPagamento,
)
from app.messaging.envelope import Envelope
from app.messaging.tracing import record_event
from app.payments import get_gateway
from app.payments.gateway import CheckoutRequest, PaymentInfo
from app.services import messages as m
from app.services.messages import BillingError, publish_reply

logger = logging.getLogger(__name__)


def buscar(db: Session, pagamento_id: int) -> Pagamento:
    pagamento = db.get(Pagamento, pagamento_id)
    if pagamento is None:
        raise BillingError("Pagamento não encontrado", 404)
    return pagamento


def _orcamento_do_comando(db: Session, env: Envelope) -> Orcamento | None:
    orcamento_id = env.payload.get("orcamento_id")
    orcamento = db.get(Orcamento, orcamento_id) if orcamento_id else None
    if orcamento is None and env.os_id is not None:
        orcamento = db.scalar(select(Orcamento).where(Orcamento.os_id == env.os_id))
    return orcamento


# ── SolicitarPagamento ──────────────────────────
def solicitar(db: Session, env: Envelope) -> Pagamento | None:
    orcamento = _orcamento_do_comando(db, env)
    if orcamento is None or orcamento.status != StatusOrcamento.APROVADO:
        publish_reply(
            db,
            m.PAGAMENTO_RECUSADO,
            {"pagamento_id": None, "status_detail": "orcamento_nao_aprovado"},
            origem=env,
        )
        return None

    # Idempotência: reaproveita cobrança pendente/aprovada do mesmo orçamento.
    for existente in orcamento.pagamentos:
        if existente.status in (StatusPagamento.PENDENTE, StatusPagamento.APROVADO):
            publish_reply(
                db,
                m.PAGAMENTO_SOLICITADO,
                {"pagamento_id": existente.id, "checkout_url": existente.checkout_url},
                origem=env,
            )
            return existente

    gateway = get_gateway()
    pagamento = Pagamento(
        orcamento_id=orcamento.id,
        status=StatusPagamento.PENDENTE,
        valor=orcamento.valor_total,  # valor do próprio Billing, não do comando
        gateway=gateway.name,
    )
    db.add(pagamento)
    db.flush()

    checkout = gateway.create_checkout(
        CheckoutRequest(
            pagamento_id=pagamento.id,
            orcamento_id=orcamento.id,
            os_id=orcamento.os_id,
            descricao=env.payload.get("descricao")
            or f"Oficina - OS #{orcamento.os_id}",
            valor=orcamento.valor_total,
            payer_email=orcamento.cliente_email
            if gateway.name == "mercadopago"
            else None,
        )
    )
    pagamento.mp_preference_id = checkout.preference_id
    pagamento.checkout_url = checkout.checkout_url
    publish_reply(
        db,
        m.PAGAMENTO_SOLICITADO,
        {"pagamento_id": pagamento.id, "checkout_url": checkout.checkout_url},
        origem=env,
    )
    return pagamento


# ── Notificação do provedor (webhook / reconciliação / simulação) ──
def processar_pagamento(db: Session, info: PaymentInfo) -> Pagamento | None:
    """Aplica o status reconsultado no provedor. Não faz commit."""
    try:
        pagamento_id = int(info.external_reference or "")
    except ValueError:
        logger.warning("Pagamento MP %s sem external_reference válido", info.payment_id)
        return None
    pagamento = db.get(Pagamento, pagamento_id)
    if pagamento is None:
        logger.warning(
            "Pagamento %s (MP %s) desconhecido", pagamento_id, info.payment_id
        )
        return None

    novo = MP_STATUS.get(info.status, StatusPagamento.PENDENTE)
    if pagamento.status in (StatusPagamento.APROVADO, StatusPagamento.ESTORNADO):
        return pagamento  # já tratado: notificações repetidas são ignoradas
    if novo == StatusPagamento.PENDENTE:
        return pagamento

    orcamento = pagamento.orcamento
    pagamento.mp_payment_id = info.payment_id
    pagamento.status_detail = info.status_detail
    pagamento.metodo = info.method
    pagamento.raw_response = info.raw

    if novo == StatusPagamento.APROVADO:
        if (
            orcamento.status in ORCAMENTO_ENCERRADO
            or pagamento.status == StatusPagamento.CANCELADO
        ):
            # Pago depois de a saga ter cancelado: devolve o dinheiro na hora.
            refund = get_gateway().refund(info.payment_id)
            pagamento.status = StatusPagamento.ESTORNADO
            pagamento.mp_refund_id = refund.refund_id
            logger.warning(
                "Pagamento tardio %s estornado automaticamente", pagamento.id
            )
            record_event(
                "PagamentoEvent",
                {"action": "estorno_automatico", "pagamento_id": pagamento.id},
            )
            return pagamento
        pagamento.status = StatusPagamento.APROVADO
        publish_reply(
            db,
            m.PAGAMENTO_CONFIRMADO,
            {
                "pagamento_id": pagamento.id,
                "mp_payment_id": info.payment_id,
                "valor": str(pagamento.valor),
                "metodo": info.method,
            },
            orcamento=orcamento,
            kind="event",
        )
        record_event(
            "PagamentoEvent",
            {
                "action": "aprovado",
                "pagamento_id": pagamento.id,
                "valor": float(pagamento.valor),
            },
        )
    elif (
        novo == StatusPagamento.RECUSADO
        and pagamento.status == StatusPagamento.PENDENTE
    ):
        pagamento.status = StatusPagamento.RECUSADO
        publish_reply(
            db,
            m.PAGAMENTO_RECUSADO,
            {"pagamento_id": pagamento.id, "status_detail": info.status_detail},
            orcamento=orcamento,
            kind="event",
        )
        record_event(
            "PagamentoEvent", {"action": "recusado", "pagamento_id": pagamento.id}
        )
    elif novo == StatusPagamento.ESTORNADO:
        pagamento.status = StatusPagamento.ESTORNADO
    return pagamento


def processar_notificacao(db: Session, payment_id: str) -> Pagamento | None:
    """Webhook: reconsulta o pagamento no provedor e aplica (com commit)."""
    info = get_gateway().get_payment(payment_id)
    pagamento = processar_pagamento(db, info)
    db.commit()
    return pagamento


def simular(db: Session, pagamento_id: int, status: str) -> Pagamento:
    """Somente PAYMENT_GATEWAY=fake: imita o pagamento + webhook do MP."""
    gateway = get_gateway()
    if gateway.name != "fake":
        raise BillingError("Simulação disponível apenas com PAYMENT_GATEWAY=fake", 400)
    pagamento = buscar(db, pagamento_id)
    info = gateway.simulate(str(pagamento.id), status, pagamento.valor)  # type: ignore[attr-defined]
    processar_pagamento(db, info)
    db.commit()
    db.refresh(pagamento)
    return pagamento


def reconciliar_pendentes(db: Session, idade_minima_segundos: int = 30) -> int:
    """Fallback ao webhook: consulta no provedor cobranças pendentes."""
    limite = datetime.now(timezone.utc) - timedelta(seconds=idade_minima_segundos)
    pendentes = db.scalars(
        select(Pagamento).where(
            Pagamento.status == StatusPagamento.PENDENTE,
            Pagamento.created_at <= limite,
        )
    ).all()
    gateway = get_gateway()
    atualizados = 0
    for pagamento in pendentes:
        info = gateway.find_payment_by_reference(str(pagamento.id))
        if info is None:
            continue
        if (
            processar_pagamento(db, info) is not None
            and pagamento.status != StatusPagamento.PENDENTE
        ):
            atualizados += 1
        db.commit()
    return atualizados


# ── Compensação EstornarPagamento ───────────────
def estornar(db: Session, env: Envelope) -> None:
    pagamento: Pagamento | None = None
    pagamento_id = env.payload.get("pagamento_id")
    if pagamento_id:
        pagamento = db.get(Pagamento, pagamento_id)
    if pagamento is None or pagamento.status != StatusPagamento.APROVADO:
        orcamento = _orcamento_do_comando(db, env)
        if orcamento is not None:
            pagamento = next(
                (
                    p
                    for p in orcamento.pagamentos
                    if p.status == StatusPagamento.APROVADO
                ),
                pagamento,
            )

    if pagamento is None or pagamento.status != StatusPagamento.APROVADO:
        # Nada a estornar (nunca foi pago ou já estornado): resposta idempotente.
        publish_reply(
            db,
            m.PAGAMENTO_ESTORNADO,
            {
                "pagamento_id": pagamento.id if pagamento else pagamento_id,
                "mp_refund_id": pagamento.mp_refund_id if pagamento else None,
                "estorno_necessario": False,
            },
            origem=env,
        )
        return

    refund = get_gateway().refund(pagamento.mp_payment_id)  # falha -> retry via SQS
    pagamento.status = StatusPagamento.ESTORNADO
    pagamento.mp_refund_id = refund.refund_id
    publish_reply(
        db,
        m.PAGAMENTO_ESTORNADO,
        {
            "pagamento_id": pagamento.id,
            "mp_refund_id": refund.refund_id,
            "estorno_necessario": True,
        },
        origem=env,
    )
    record_event(
        "PagamentoEvent", {"action": "estornado", "pagamento_id": pagamento.id}
    )
