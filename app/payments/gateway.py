"""Porta de pagamentos. Implementações: Mercado Pago (sandbox/produção) e Fake."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


class PaymentGatewayError(Exception):
    """Falha de comunicação/negócio com o provedor de pagamento."""


@dataclass
class CheckoutRequest:
    pagamento_id: int
    orcamento_id: int
    os_id: int
    descricao: str
    valor: Decimal
    payer_email: str | None = None


@dataclass
class CheckoutResult:
    preference_id: str
    checkout_url: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentInfo:
    payment_id: str
    status: str  # status do provedor (approved, rejected, pending, refunded...)
    status_detail: str | None
    external_reference: str | None
    amount: Decimal | None
    method: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RefundResult:
    refund_id: str
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentGateway(Protocol):
    name: str

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult: ...

    def get_payment(self, payment_id: str) -> PaymentInfo: ...

    def refund(self, payment_id: str) -> RefundResult: ...

    def find_payment_by_reference(
        self, external_reference: str
    ) -> PaymentInfo | None: ...
