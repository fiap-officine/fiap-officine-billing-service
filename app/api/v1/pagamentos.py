import logging

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, ensure_owner, get_principal
from app.config import get_settings
from app.domain.entities.billing import Orcamento, Pagamento
from app.infrastructure.database import get_db
from app.messaging.tracing import record_event
from app.payments.gateway import PaymentGatewayError
from app.payments.signature import is_valid_signature
from app.schemas import PagamentoResponse, SimularPagamentoRequest
from app.services import pagamento_service
from app.services.messages import BillingError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pagamentos", tags=["Pagamentos (Mercado Pago)"])


@router.post("/webhook", status_code=200)
def webhook_mercado_pago(
    body: dict = Body(default_factory=dict),
    data_id: str | None = Query(None, alias="data.id"),
    tipo: str | None = Query(None, alias="type"),
    x_signature: str | None = Header(None, alias="x-signature"),
    x_request_id: str | None = Header(None, alias="x-request-id"),
    db: Session = Depends(get_db),
):
    """Notificação do Mercado Pago (rota **pública** no API Gateway, sem JWT).

    1. Valida `x-signature` (HMAC-SHA256 com a assinatura secreta da aplicação).
    2. Reconsulta `GET /v1/payments/{id}` — nunca confia no corpo da notificação.
    3. Atualiza o pagamento e publica `PagamentoConfirmado`/`PagamentoRecusado`.
    """
    data_id = data_id or str((body.get("data") or {}).get("id") or "") or None
    tipo = tipo or body.get("type") or body.get("topic")

    secret = get_settings().MP_WEBHOOK_SECRET
    if secret and not is_valid_signature(secret, x_signature, x_request_id, data_id):
        record_event(
            "WebhookRejected", {"reason": "invalid_signature", "data_id": data_id}
        )
        raise HTTPException(status_code=401, detail="Assinatura inválida")

    if tipo != "payment" or not data_id:
        return {"status": "ignorado", "type": tipo}

    try:
        pagamento = pagamento_service.processar_notificacao(db, data_id)
    except PaymentGatewayError as exc:
        # 5xx faz o Mercado Pago reenviar a notificação depois.
        logger.error("Falha ao consultar pagamento %s no MP: %s", data_id, exc)
        raise HTTPException(
            status_code=502, detail="Falha ao consultar o Mercado Pago"
        ) from exc
    return {
        "status": "processado",
        "pagamento_id": pagamento.id if pagamento else None,
        "situacao": pagamento.status.value if pagamento else None,
    }


@router.get("/", response_model=list[PagamentoResponse])
def listar_pagamentos(
    orcamento_id: int = Query(...),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    orcamento = db.get(Orcamento, orcamento_id)
    if orcamento is None:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado")
    ensure_owner(principal, orcamento)
    return list(
        db.scalars(
            select(Pagamento).where(Pagamento.orcamento_id == orcamento_id)
        ).all()
    )


@router.get("/{pagamento_id}", response_model=PagamentoResponse)
def buscar_pagamento(
    pagamento_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Status da cobrança e link do checkout (Checkout Pro / Pix)."""
    try:
        pagamento = pagamento_service.buscar(db, pagamento_id)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    ensure_owner(principal, pagamento.orcamento)
    return pagamento


@router.post("/{pagamento_id}/simular", response_model=PagamentoResponse)
def simular_pagamento(
    pagamento_id: int,
    dados: SimularPagamentoRequest = Body(default_factory=SimularPagamentoRequest),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """**Somente PAYMENT_GATEWAY=fake** (dev/testes): simula o pagamento no
    provedor e a notificação do webhook."""
    try:
        pagamento = pagamento_service.buscar(db, pagamento_id)
        ensure_owner(principal, pagamento.orcamento)
        return pagamento_service.simular(db, pagamento_id, dados.status)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
