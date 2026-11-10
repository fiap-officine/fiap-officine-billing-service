"""Registra todos os modelos no metadata do SQLAlchemy."""

from app.domain.entities.billing import Orcamento, OrcamentoItem, Pagamento  # noqa: F401
from app.domain.entities.messaging import OutboxMessage, ProcessedMessage  # noqa: F401
