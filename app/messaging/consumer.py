"""Consumer SQS idempotente.

Cada mensagem é processada dentro de uma transação que também grava o
`message_id` em `processed_messages`. Duplicatas (SQS é at-least-once) são
detectadas antes do processamento ou pela violação da PK no commit.
Exceções não tratadas deixam a mensagem na fila: ela volta após o
visibility timeout e, depois de `maxReceiveCount` tentativas, vai para a DLQ.
"""

import json
import logging
from collections.abc import Callable
from typing import Literal

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import correlation_id_ctx, os_id_ctx, saga_id_ctx
from app.domain.entities.messaging import ProcessedMessage
from app.messaging.envelope import Envelope
from app.messaging.sqs import SqsBus
from app.messaging.tracing import (
    accept_trace_headers,
    add_attributes,
    background_transaction,
    record_event,
)

logger = logging.getLogger(__name__)

Handler = Callable[[Session, Envelope], None]
Outcome = Literal["processed", "duplicate", "invalid"]


def already_processed(db: Session, message_id: str) -> bool:
    return db.get(ProcessedMessage, message_id) is not None


def handle_message(db: Session, body: str, handler: Handler) -> Outcome:
    try:
        envelope = Envelope.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error("Mensagem inválida descartada: %s", exc)
        record_event("MessageRejected", {"reason": str(exc)[:255]})
        return "invalid"

    tokens = (
        correlation_id_ctx.set(envelope.correlation_id),
        saga_id_ctx.set(envelope.saga_id),
        os_id_ctx.set(envelope.os_id),
    )
    try:
        with background_transaction(f"consume/{envelope.type}"):
            accept_trace_headers(envelope.trace)
            add_attributes(
                {
                    "saga_id": envelope.saga_id,
                    "os_id": envelope.os_id,
                    "message_type": envelope.type,
                    "correlation_id": envelope.correlation_id,
                }
            )
            if already_processed(db, envelope.message_id):
                logger.info(
                    "Mensagem duplicada ignorada",
                    extra={
                        "message_id": envelope.message_id,
                        "message_type": envelope.type,
                    },
                )
                return "duplicate"
            try:
                handler(db, envelope)
                db.add(
                    ProcessedMessage(
                        message_id=envelope.message_id, message_type=envelope.type
                    )
                )
                db.commit()
            except IntegrityError:
                db.rollback()
                if already_processed(db, envelope.message_id):
                    return "duplicate"
                raise
            except Exception:
                db.rollback()
                raise
            logger.info(
                "Mensagem %s processada",
                envelope.type,
                extra={
                    "message_id": envelope.message_id,
                    "message_type": envelope.type,
                },
            )
            return "processed"
    finally:
        correlation_id_ctx.reset(tokens[0])
        saga_id_ctx.reset(tokens[1])
        os_id_ctx.reset(tokens[2])


def poll_once(
    bus: SqsBus,
    queue: str,
    session_factory: Callable[[], Session],
    handler: Handler,
    wait_seconds: int | None = None,
) -> int:
    """Recebe um lote do SQS e processa. Retorna o nº de mensagens tratadas."""
    handled = 0
    for raw in bus.receive(queue, wait_seconds=wait_seconds):
        db = session_factory()
        try:
            handle_message(db, raw["Body"], handler)
            bus.delete(queue, raw["ReceiptHandle"])
            handled += 1
        except Exception as exc:
            logger.error(
                "Erro ao processar mensagem (ficará para retry/DLQ): %s",
                exc,
                exc_info=True,
                extra={"queue": queue},
            )
            record_event(
                "MessageProcessingFailure", {"queue": queue, "error": str(exc)[:255]}
            )
        finally:
            db.close()
    return handled
