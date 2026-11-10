import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.billing import Orcamento
from app.domain.entities.messaging import OutboxMessage
from app.handlers import billing_command_handler
from app.messaging.consumer import handle_message
from app.messaging.envelope import new_envelope

SAGA_ID = str(uuid.uuid4())


def comando(tipo: str, payload: dict, os_id: int = 1, saga_id: str = SAGA_ID):
    return new_envelope(
        tipo, "command", payload, source="os-service", saga_id=saga_id, os_id=os_id
    )


def processar(db: Session, tipo: str, payload: dict, os_id: int = 1):
    env = comando(tipo, payload, os_id)
    resultado = handle_message(db, env.model_dump_json(), billing_command_handler)
    db.expire_all()
    return resultado


def respostas(db: Session) -> list[OutboxMessage]:
    db.expire_all()
    return list(db.scalars(select(OutboxMessage).order_by(OutboxMessage.id)).all())


def tipos_respondidos(db: Session) -> list[str]:
    return [r.message_type for r in respostas(db)]


def payload_gerar(cliente_id: int = 7, itens=None) -> dict:
    return {
        "cliente": {"id": cliente_id, "nome": "Maria", "email": "maria@test.com"},
        "veiculo": {"id": 3, "placa": "ABC1234"},
        "itens": itens
        if itens is not None
        else [
            {
                "tipo": "servico",
                "ref_id": 1,
                "descricao": "Troca de óleo",
                "quantidade": 1,
                "valor_unitario": "150.00",
            },
            {
                "tipo": "peca",
                "ref_id": 2,
                "descricao": "Filtro",
                "quantidade": 2,
                "valor_unitario": "35.50",
            },
        ],
    }


def orcamento_gerado(db: Session, os_id: int = 1, cliente_id: int = 7) -> Orcamento:
    processar(db, "GerarOrcamento", payload_gerar(cliente_id), os_id)
    return db.scalar(select(Orcamento).where(Orcamento.os_id == os_id))


def orcamento_aprovado(db: Session, client, headers, os_id: int = 1) -> Orcamento:
    orcamento = orcamento_gerado(db, os_id)
    resp = client.post(f"/api/v1/orcamentos/{orcamento.id}/aprovar", headers=headers)
    assert resp.status_code == 200, resp.text
    db.expire_all()
    return orcamento


def pagamento_solicitado(db: Session, client, headers, os_id: int = 1):
    orcamento = orcamento_aprovado(db, client, headers, os_id)
    processar(
        db,
        "SolicitarPagamento",
        {"orcamento_id": orcamento.id, "valor": "221.00"},
        os_id,
    )
    db.expire_all()
    return orcamento, orcamento.pagamentos[-1]
