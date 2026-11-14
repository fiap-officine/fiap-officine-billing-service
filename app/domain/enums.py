import enum


class StatusOrcamento(str, enum.Enum):
    GERADO = "gerado"
    APROVADO = "aprovado"
    RECUSADO = "recusado"
    CANCELADO = "cancelado"
    EXPIRADO = "expirado"


class StatusPagamento(str, enum.Enum):
    PENDENTE = "pendente"
    APROVADO = "aprovado"
    RECUSADO = "recusado"
    ESTORNADO = "estornado"
    CANCELADO = "cancelado"


ORCAMENTO_ENCERRADO = {
    StatusOrcamento.RECUSADO,
    StatusOrcamento.CANCELADO,
    StatusOrcamento.EXPIRADO,
}

# Status do Mercado Pago -> status interno
MP_STATUS = {
    "approved": StatusPagamento.APROVADO,
    "authorized": StatusPagamento.PENDENTE,
    "pending": StatusPagamento.PENDENTE,
    "in_process": StatusPagamento.PENDENTE,
    "in_mediation": StatusPagamento.PENDENTE,
    "rejected": StatusPagamento.RECUSADO,
    "cancelled": StatusPagamento.RECUSADO,
    "refunded": StatusPagamento.ESTORNADO,
    "charged_back": StatusPagamento.ESTORNADO,
}
