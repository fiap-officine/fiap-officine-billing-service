"""Orçamentos: geração (comando da saga), aprovação/recusa (cliente) e
cancelamento (compensação)."""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.entities.billing import Orcamento, OrcamentoItem
from app.domain.enums import StatusOrcamento, StatusPagamento
from app.messaging.envelope import Envelope
from app.messaging.tracing import record_event
from app.services import messages as m
from app.services.messages import BillingError, publish_reply

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def buscar_por_os(db: Session, os_id: int) -> Orcamento | None:
    return db.scalar(select(Orcamento).where(Orcamento.os_id == os_id))


def buscar(db: Session, orcamento_id: int) -> Orcamento:
    orcamento = db.get(Orcamento, orcamento_id)
    if orcamento is None:
        raise BillingError("Orçamento não encontrado", 404)
    return orcamento


def _payload_gerado(orcamento: Orcamento) -> dict:
    return {
        "orcamento_id": orcamento.id,
        "valor_total": str(orcamento.valor_total),
        "expira_em": _aware(orcamento.expira_em).isoformat(),
    }


def gerar(db: Session, env: Envelope) -> Orcamento | None:
    """Handler de `GerarOrcamento` (idempotente por os_id)."""
    existente = buscar_por_os(db, env.os_id)
    if existente is not None:
        publish_reply(db, m.ORCAMENTO_GERADO, _payload_gerado(existente), origem=env)
        return existente

    itens_payload = env.payload.get("itens") or []
    cliente = env.payload.get("cliente") or {}
    try:
        itens = [
            OrcamentoItem(
                tipo=i["tipo"],
                ref_id=int(i["ref_id"]),
                descricao=i.get("descricao"),
                quantidade=int(i["quantidade"]),
                valor_unitario=Decimal(str(i["valor_unitario"])),
                valor_total=Decimal(str(i["valor_unitario"])) * int(i["quantidade"]),
            )
            for i in itens_payload
        ]
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        publish_reply(
            db, m.ORCAMENTO_FALHOU, {"motivo": f"Itens inválidos: {exc}"}, origem=env
        )
        return None

    total = sum((i.valor_total for i in itens), Decimal("0"))
    if (
        not itens
        or total <= 0
        or any(i.quantidade <= 0 for i in itens)
        or not cliente.get("id")
    ):
        publish_reply(
            db,
            m.ORCAMENTO_FALHOU,
            {"motivo": "Orçamento sem itens, com valor zerado ou sem cliente"},
            origem=env,
        )
        return None

    orcamento = Orcamento(
        os_id=env.os_id,
        saga_id=env.saga_id,
        cliente_id=int(cliente["id"]),
        cliente_nome=cliente.get("nome"),
        cliente_email=cliente.get("email"),
        status=StatusOrcamento.GERADO,
        valor_total=total,
        expira_em=_now() + timedelta(hours=get_settings().ORCAMENTO_VALIDADE_HORAS),
        itens=itens,
    )
    db.add(orcamento)
    db.flush()
    publish_reply(db, m.ORCAMENTO_GERADO, _payload_gerado(orcamento), origem=env)
    record_event(
        "OrcamentoEvent",
        {
            "action": "gerado",
            "orcamento_id": orcamento.id,
            "os_id": orcamento.os_id,
            "valor_total": float(total),
        },
    )
    return orcamento


def aprovar(db: Session, orcamento_id: int) -> Orcamento:
    orcamento = buscar(db, orcamento_id)
    _validar_decisao(db, orcamento)
    orcamento.status = StatusOrcamento.APROVADO
    orcamento.decidido_em = _now()
    publish_reply(
        db,
        m.ORCAMENTO_APROVADO,
        {"orcamento_id": orcamento.id},
        orcamento=orcamento,
        kind="event",
    )
    db.commit()
    db.refresh(orcamento)
    record_event("OrcamentoEvent", {"action": "aprovado", "orcamento_id": orcamento.id})
    return orcamento


def recusar(db: Session, orcamento_id: int, motivo: str | None) -> Orcamento:
    orcamento = buscar(db, orcamento_id)
    _validar_decisao(db, orcamento)
    orcamento.status = StatusOrcamento.RECUSADO
    orcamento.decidido_em = _now()
    orcamento.motivo = (motivo or "Recusado pelo cliente")[:500]
    publish_reply(
        db,
        m.ORCAMENTO_RECUSADO,
        {"orcamento_id": orcamento.id, "motivo": orcamento.motivo},
        orcamento=orcamento,
        kind="event",
    )
    db.commit()
    db.refresh(orcamento)
    record_event("OrcamentoEvent", {"action": "recusado", "orcamento_id": orcamento.id})
    return orcamento


def _validar_decisao(db: Session, orcamento: Orcamento) -> None:
    if orcamento.status != StatusOrcamento.GERADO:
        raise BillingError(
            f"Orçamento já está '{orcamento.status.value}' e não pode ser decidido"
        )
    if _aware(orcamento.expira_em) < _now():
        orcamento.status = StatusOrcamento.EXPIRADO
        db.commit()
        raise BillingError("Orçamento expirado", 410)


def cancelar(db: Session, env: Envelope) -> None:
    """Compensação `CancelarOrcamento` (idempotente; também cancela cobranças
    pendentes)."""
    orcamento_id = env.payload.get("orcamento_id")
    orcamento = db.get(Orcamento, orcamento_id) if orcamento_id else None
    if orcamento is None and env.os_id is not None:
        orcamento = buscar_por_os(db, env.os_id)

    if orcamento is not None:
        if orcamento.status in (StatusOrcamento.GERADO, StatusOrcamento.APROVADO):
            orcamento.status = StatusOrcamento.CANCELADO
            orcamento.motivo = (env.payload.get("motivo") or "Cancelado pela saga")[
                :500
            ]
        for pagamento in orcamento.pagamentos:
            if pagamento.status == StatusPagamento.PENDENTE:
                pagamento.status = StatusPagamento.CANCELADO

    publish_reply(
        db,
        m.ORCAMENTO_CANCELADO,
        {"orcamento_id": orcamento.id if orcamento else None},
        origem=env,
    )
