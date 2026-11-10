from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import StatusOrcamento, StatusPagamento


class OrcamentoItemResponse(BaseModel):
    id: int
    tipo: str
    ref_id: int
    descricao: str | None
    quantidade: int
    valor_unitario: Decimal
    valor_total: Decimal

    model_config = {"from_attributes": True}


class PagamentoResponse(BaseModel):
    id: int
    orcamento_id: int
    status: StatusPagamento
    valor: Decimal
    metodo: str | None
    gateway: str
    checkout_url: str | None
    mp_payment_id: str | None
    mp_refund_id: str | None
    status_detail: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrcamentoResponse(BaseModel):
    id: int
    os_id: int
    cliente_id: int
    status: StatusOrcamento
    valor_total: Decimal
    expira_em: datetime
    motivo: str | None
    decidido_em: datetime | None
    created_at: datetime
    itens: list[OrcamentoItemResponse]
    pagamentos: list[PagamentoResponse]

    model_config = {"from_attributes": True}


class RecusarRequest(BaseModel):
    motivo: str | None = Field(None, max_length=500)


class SimularPagamentoRequest(BaseModel):
    status: str = Field("approved", pattern="^(approved|rejected)$")
