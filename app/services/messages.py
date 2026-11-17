"""Contratos de mensagens usados pelo Billing (ver docs/contracts)."""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.entities.billing import Orcamento
from app.messaging import outbox
from app.messaging.envelope import Envelope, new_envelope

BILLING_COMMANDS = "billing-commands"
OS_REPLIES = "os-saga-replies"

# Comandos recebidos
GERAR_ORCAMENTO = "GerarOrcamento"
SOLICITAR_PAGAMENTO = "SolicitarPagamento"
ESTORNAR_PAGAMENTO = "EstornarPagamento"
CANCELAR_ORCAMENTO = "CancelarOrcamento"

# Respostas / eventos publicados
ORCAMENTO_GERADO = "OrcamentoGerado"
ORCAMENTO_FALHOU = "OrcamentoFalhou"
ORCAMENTO_APROVADO = "OrcamentoAprovado"
ORCAMENTO_RECUSADO = "OrcamentoRecusado"
ORCAMENTO_CANCELADO = "OrcamentoCancelado"
PAGAMENTO_SOLICITADO = "PagamentoSolicitado"
PAGAMENTO_CONFIRMADO = "PagamentoConfirmado"
PAGAMENTO_RECUSADO = "PagamentoRecusado"
PAGAMENTO_ESTORNADO = "PagamentoEstornado"


class BillingError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def publish_reply(
    db: Session,
    message_type: str,
    payload: dict,
    *,
    origem: Envelope | None = None,
    orcamento: Orcamento | None = None,
    kind: str = "reply",
) -> Envelope:
    """Grava uma resposta/evento para o orquestrador no outbox (sem commit)."""
    saga_id = origem.saga_id if origem else (orcamento.saga_id if orcamento else None)
    os_id = origem.os_id if origem else (orcamento.os_id if orcamento else None)
    envelope = new_envelope(
        message_type,
        kind,  # type: ignore[arg-type]
        payload,
        source=get_settings().SERVICE_NAME,
        saga_id=saga_id,
        os_id=os_id,
        correlation_id=origem.correlation_id if origem else None,
    )
    outbox.enqueue(db, OS_REPLIES, envelope)
    return envelope
