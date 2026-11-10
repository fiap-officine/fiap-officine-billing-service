"""Gateway fake para desenvolvimento local e testes (PAYMENT_GATEWAY=fake).

Os "pagamentos" ficam em memória e são criados pelo endpoint
`POST /api/v1/pagamentos/{id}/simular`, que imita o webhook do Mercado Pago.
"""

import itertools
import threading
from decimal import Decimal

from app.payments.gateway import (
    CheckoutRequest,
    CheckoutResult,
    PaymentGatewayError,
    PaymentInfo,
    RefundResult,
)


class FakeGateway:
    name = "fake"

    def __init__(self):
        self._payments: dict[str, PaymentInfo] = {}
        self._ids = itertools.count(1000)
        self._lock = threading.Lock()
        self.refunds: list[str] = []
        self.fail_next_refund = False

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        return CheckoutResult(
            preference_id=f"fake-pref-{request.pagamento_id}",
            checkout_url=f"/api/v1/pagamentos/{request.pagamento_id}/simular",
            raw={"fake": True},
        )

    def simulate(
        self,
        external_reference: str,
        status: str,
        amount: Decimal,
        method: str = "pix",
    ) -> PaymentInfo:
        with self._lock:
            payment_id = str(next(self._ids))
            info = PaymentInfo(
                payment_id=payment_id,
                status=status,
                status_detail="accredited"
                if status == "approved"
                else "cc_rejected_other_reason",
                external_reference=external_reference,
                amount=amount,
                method=method,
                raw={"id": payment_id, "status": status, "fake": True},
            )
            self._payments[payment_id] = info
            return info

    def get_payment(self, payment_id: str) -> PaymentInfo:
        try:
            return self._payments[payment_id]
        except KeyError as exc:
            raise PaymentGatewayError(f"Pagamento {payment_id} não encontrado") from exc

    def refund(self, payment_id: str) -> RefundResult:
        if self.fail_next_refund:
            self.fail_next_refund = False
            raise PaymentGatewayError("Falha simulada no estorno")
        info = self.get_payment(payment_id)
        info.status = "refunded"
        self.refunds.append(payment_id)
        return RefundResult(refund_id=f"fake-refund-{payment_id}", raw={"fake": True})

    def find_payment_by_reference(self, external_reference: str) -> PaymentInfo | None:
        matches = [
            p
            for p in self._payments.values()
            if p.external_reference == external_reference
        ]
        return matches[-1] if matches else None
