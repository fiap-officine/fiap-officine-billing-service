"""Integração com o Mercado Pago (Checkout Pro) via SDK oficial `mercadopago`.

- Cobrança: preferência com `external_reference = pagamento_id` e
  `notification_url` apontando para o webhook público do Billing.
- Confirmação: o webhook só informa o ID; o status é SEMPRE reconsultado em
  `GET /v1/payments/{id}` (nunca confiar no corpo do webhook).
- Compensação: estorno total em `POST /v1/payments/{id}/refunds`.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.config import Settings, get_settings
from app.payments.gateway import (
    CheckoutRequest,
    CheckoutResult,
    PaymentGatewayError,
    PaymentInfo,
    RefundResult,
)


def _ok(response: dict[str, Any], operation: str) -> dict[str, Any]:
    status = response.get("status")
    body = response.get("response") or {}
    if not isinstance(status, int) or status >= 400:
        message = body.get("message") if isinstance(body, dict) else body
        raise PaymentGatewayError(
            f"Mercado Pago {operation} falhou ({status}): {message}"
        )
    return body


def _to_info(body: dict[str, Any]) -> PaymentInfo:
    amount = body.get("transaction_amount")
    return PaymentInfo(
        payment_id=str(body.get("id")),
        status=str(body.get("status")),
        status_detail=body.get("status_detail"),
        external_reference=body.get("external_reference"),
        amount=Decimal(str(amount)) if amount is not None else None,
        method=body.get("payment_method_id") or body.get("payment_type_id"),
        raw=body,
    )


class MercadoPagoGateway:
    name = "mercadopago"

    def __init__(self, settings: Settings | None = None, sdk: Any | None = None):
        self.settings = settings or get_settings()
        if sdk is None:
            if not self.settings.MP_ACCESS_TOKEN:
                raise PaymentGatewayError("MP_ACCESS_TOKEN não configurado")
            import mercadopago

            sdk = mercadopago.SDK(self.settings.MP_ACCESS_TOKEN)
        self.sdk = sdk

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        expira = datetime.now(timezone.utc) + timedelta(
            minutes=self.settings.PAYMENT_EXPIRATION_MINUTES
        )
        preference: dict[str, Any] = {
            "items": [
                {
                    "id": str(request.orcamento_id),
                    "title": request.descricao,
                    "quantity": 1,
                    "currency_id": "BRL",
                    "unit_price": float(request.valor),
                }
            ],
            "external_reference": str(request.pagamento_id),
            "metadata": {
                "pagamento_id": request.pagamento_id,
                "orcamento_id": request.orcamento_id,
                "os_id": request.os_id,
            },
            "expires": True,
            "expiration_date_to": expira.isoformat(timespec="milliseconds"),
            "statement_descriptor": "OFICINA",
        }
        if self.settings.MP_NOTIFICATION_URL:
            preference["notification_url"] = self.settings.MP_NOTIFICATION_URL
        if request.payer_email:
            preference["payer"] = {"email": request.payer_email}

        body = _ok(self.sdk.preference().create(preference), "create_preference")
        url = (
            body.get("sandbox_init_point")
            if self.settings.MP_USE_SANDBOX_URL
            else body.get("init_point")
        ) or body.get("init_point")
        return CheckoutResult(preference_id=str(body["id"]), checkout_url=url, raw=body)

    def get_payment(self, payment_id: str) -> PaymentInfo:
        return _to_info(_ok(self.sdk.payment().get(payment_id), "get_payment"))

    def refund(self, payment_id: str) -> RefundResult:
        body = _ok(self.sdk.refund().create(payment_id), "refund")
        return RefundResult(refund_id=str(body.get("id")), raw=body)

    def find_payment_by_reference(self, external_reference: str) -> PaymentInfo | None:
        body = _ok(
            self.sdk.payment().search(
                {
                    "external_reference": external_reference,
                    "sort": "date_created",
                    "criteria": "desc",
                }
            ),
            "search_payment",
        )
        results = body.get("results") or []
        return _to_info(results[0]) if results else None
