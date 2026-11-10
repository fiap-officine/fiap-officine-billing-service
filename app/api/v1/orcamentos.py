from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, ensure_owner, get_principal
from app.domain.entities.billing import Orcamento
from app.infrastructure.database import get_db
from app.schemas import OrcamentoResponse, RecusarRequest
from app.services import orcamento_service
from app.services.messages import BillingError

router = APIRouter(prefix="/orcamentos", tags=["Orçamentos"])


def _carregar(db: Session, orcamento_id: int, principal: Principal) -> Orcamento:
    try:
        orcamento = orcamento_service.buscar(db, orcamento_id)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    ensure_owner(principal, orcamento)
    return orcamento


@router.get("/", response_model=list[OrcamentoResponse])
def listar_orcamentos(
    os_id: int | None = Query(None),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Lista orçamentos (cliente vê apenas os próprios). Filtro por OS."""
    stmt = select(Orcamento).order_by(Orcamento.id.desc()).limit(100)
    if os_id is not None:
        stmt = stmt.where(Orcamento.os_id == os_id)
    if not principal.is_admin:
        stmt = stmt.where(Orcamento.cliente_id == (principal.cliente_id or -1))
    return list(db.scalars(stmt).all())


@router.get("/{orcamento_id}", response_model=OrcamentoResponse)
def buscar_orcamento(
    orcamento_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    return _carregar(db, orcamento_id, principal)


@router.post("/{orcamento_id}/aprovar", response_model=OrcamentoResponse)
def aprovar_orcamento(
    orcamento_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Cliente aprova o orçamento -> evento `OrcamentoAprovado` para a saga, que
    então solicita o pagamento no Mercado Pago."""
    _carregar(db, orcamento_id, principal)
    try:
        return orcamento_service.aprovar(db, orcamento_id)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{orcamento_id}/recusar", response_model=OrcamentoResponse)
def recusar_orcamento(
    orcamento_id: int,
    dados: RecusarRequest | None = None,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Cliente recusa -> evento `OrcamentoRecusado`; a saga compensa e cancela a OS."""
    _carregar(db, orcamento_id, principal)
    try:
        return orcamento_service.recusar(
            db, orcamento_id, dados.motivo if dados else None
        )
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
