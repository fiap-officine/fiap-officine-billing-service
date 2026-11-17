"""Transactional Outbox.

`enqueue` grava a mensagem na tabela `outbox` dentro da transação corrente
(sem commit). `relay_pending` publica as pendentes no SQS e marca como enviadas.
Se o processo cair entre o commit e o publish, a mensagem continua `pending` e
será publicada na próxima volta — nunca é perdida (substitui o antigo
`try: publicar_notificacao(...) except: pass`).
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.messaging import OutboxMessage
from app.messaging.envelope import Envelope
from app.messaging.sqs import SqsBus
from app.messaging.tracing import inject_trace_headers

logger = logging.getLogger(__name__)


def enqueue(db: Session, destination: str, envelope: Envelope) -> OutboxMessage:
    if not envelope.trace:
        envelope.trace = inject_trace_headers()
    message = OutboxMessage(
        message_id=envelope.message_id,
        destination=destination,
        message_type=envelope.type,
        envelope=envelope.model_dump(mode="json"),
        status="pending",
        attempts=0,
    )
    db.add(message)
    return message


def relay_pending(db: Session, bus: SqsBus, batch_size: int = 50) -> int:
    """Publica mensagens pendentes. Retorna quantas foram enviadas."""
    stmt = (
        select(OutboxMessage)
        .where(OutboxMessage.status == "pending")
        .order_by(OutboxMessage.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    messages = list(db.scalars(stmt).all())
    sent = 0
    for message in messages:
        envelope = message.envelope
        try:
            bus.send(
                message.destination,
                json.dumps(envelope, ensure_ascii=False),
                {
                    "type": message.message_type,
                    "message_id": message.message_id,
                    "saga_id": envelope.get("saga_id"),
                    "source": envelope.get("source"),
                },
            )
            message.status = "sent"
            message.sent_at = datetime.now(timezone.utc)
            message.last_error = None
            sent += 1
            logger.info(
                "Mensagem %s publicada em %s",
                message.message_type,
                message.destination,
                extra={
                    "message_id": message.message_id,
                    "message_type": message.message_type,
                    "queue": message.destination,
                    "saga_id": envelope.get("saga_id"),
                    "os_id": envelope.get("os_id"),
                },
            )
        except Exception as exc:
            message.attempts += 1
            message.last_error = str(exc)[:1000]
            logger.warning(
                "Falha ao publicar mensagem do outbox: %s",
                exc,
                extra={
                    "message_id": message.message_id,
                    "message_type": message.message_type,
                    "queue": message.destination,
                },
            )
    db.commit()
    return sent
