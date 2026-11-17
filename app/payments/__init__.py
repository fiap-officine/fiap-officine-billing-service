"""Fábrica do gateway de pagamento configurado (PAYMENT_GATEWAY)."""

from app.config import get_settings
from app.payments.gateway import PaymentGateway

_gateway: PaymentGateway | None = None


def get_gateway() -> PaymentGateway:
    global _gateway
    if _gateway is None:
        settings = get_settings()
        if settings.PAYMENT_GATEWAY == "mercadopago":
            from app.payments.mercadopago_gateway import MercadoPagoGateway

            _gateway = MercadoPagoGateway(settings)
        else:
            from app.payments.fake_gateway import FakeGateway

            _gateway = FakeGateway()
    return _gateway


def set_gateway(gateway: PaymentGateway | None) -> None:
    global _gateway
    _gateway = gateway
