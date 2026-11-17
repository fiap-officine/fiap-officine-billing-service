"""Roteamento dos comandos da fila billing-commands."""

import logging

from sqlalchemy.orm import Session

from app.messaging.envelope import Envelope
from app.services import messages as m
from app.services import orcamento_service, pagamento_service

logger = logging.getLogger(__name__)

HANDLERS = {
    m.GERAR_ORCAMENTO: orcamento_service.gerar,
    m.SOLICITAR_PAGAMENTO: pagamento_service.solicitar,
    m.ESTORNAR_PAGAMENTO: pagamento_service.estornar,
    m.CANCELAR_ORCAMENTO: orcamento_service.cancelar,
}


def billing_command_handler(db: Session, envelope: Envelope) -> None:
    handler = HANDLERS.get(envelope.type)
    if handler is None:
        logger.warning("Comando desconhecido ignorado: %s", envelope.type)
        return
    handler(db, envelope)
