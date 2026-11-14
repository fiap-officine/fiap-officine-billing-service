"""Gateways de pagamento e validação de assinatura do webhook."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.payments import get_gateway, set_gateway
from app.payments.fake_gateway import FakeGateway
from app.payments.gateway import CheckoutRequest, PaymentGatewayError
from app.payments.mercadopago_gateway import MercadoPagoGateway
from app.payments.signature import (
    build_manifest,
    is_valid_signature,
    parse_signature,
    sign,
)


class TestSignature:
    def test_manifest_segue_formato_do_mercado_pago(self):
        assert (
            build_manifest("ABC123", "req-1", "1700")
            == "id:abc123;request-id:req-1;ts:1700;"
        )
        assert build_manifest(None, None, "1700") == "ts:1700;"
        assert build_manifest("12-3", None, "1") == "id:12-3;ts:1;"

    def test_parse(self):
        assert parse_signature("ts=1, v1=abc") == ("1", "abc")
        assert parse_signature(None) == (None, None)
        assert parse_signature("lixo") == (None, None)

    def test_valida_e_rejeita(self):
        v1 = sign("s3cr3t", "123", "req", "1700")
        assert is_valid_signature("s3cr3t", f"ts=1700,v1={v1}", "req", "123")
        assert not is_valid_signature("s3cr3t", f"ts=1700,v1={v1}", "req", "124")
        assert not is_valid_signature("errado", f"ts=1700,v1={v1}", "req", "123")
        assert not is_valid_signature("s3cr3t", "ts=1700", "req", "123")


def _request():
    return CheckoutRequest(
        pagamento_id=10,
        orcamento_id=5,
        os_id=3,
        descricao="OS #3",
        valor=Decimal("221.00"),
        payer_email="test_user@testuser.com",
    )


class TestMercadoPagoGateway:
    def _gateway(self, **settings):
        sdk = MagicMock()
        base = {
            "MP_ACCESS_TOKEN": "TEST-token",
            "MP_NOTIFICATION_URL": "https://api/pagamentos/webhook",
        }
        base.update(settings)
        return MercadoPagoGateway(Settings(**base), sdk=sdk), sdk

    def test_create_checkout_monta_preferencia(self):
        gw, sdk = self._gateway()
        sdk.preference.return_value.create.return_value = {
            "status": 201,
            "response": {
                "id": "pref-1",
                "init_point": "https://mp/prod",
                "sandbox_init_point": "https://mp/sandbox",
            },
        }
        result = gw.create_checkout(_request())
        assert result.preference_id == "pref-1"
        assert result.checkout_url == "https://mp/sandbox"
        enviado = sdk.preference.return_value.create.call_args.args[0]
        assert enviado["external_reference"] == "10"
        assert enviado["notification_url"] == "https://api/pagamentos/webhook"
        assert enviado["items"][0]["unit_price"] == 221.0
        assert enviado["payer"]["email"] == "test_user@testuser.com"
        assert enviado["metadata"]["os_id"] == 3

    def test_create_checkout_producao_usa_init_point(self):
        gw, sdk = self._gateway(MP_USE_SANDBOX_URL=False, MP_NOTIFICATION_URL=None)
        sdk.preference.return_value.create.return_value = {
            "status": 201,
            "response": {"id": "p", "init_point": "https://mp/prod"},
        }
        req = _request()
        req.payer_email = None
        assert gw.create_checkout(req).checkout_url == "https://mp/prod"
        enviado = sdk.preference.return_value.create.call_args.args[0]
        assert "notification_url" not in enviado and "payer" not in enviado

    def test_create_checkout_sem_email_do_pagador_no_sandbox(self):
        gw, sdk = self._gateway(MP_ENVIAR_EMAIL_PAGADOR=False)
        sdk.preference.return_value.create.return_value = {
            "status": 201,
            "response": {"id": "p", "sandbox_init_point": "https://mp/sandbox"},
        }
        gw.create_checkout(_request())
        enviado = sdk.preference.return_value.create.call_args.args[0]
        assert "payer" not in enviado

    def test_erro_do_mercado_pago(self):
        gw, sdk = self._gateway()
        sdk.preference.return_value.create.return_value = {
            "status": 400,
            "response": {"message": "invalid unit_price"},
        }
        with pytest.raises(PaymentGatewayError, match="invalid unit_price"):
            gw.create_checkout(_request())

    def test_get_payment_refund_e_busca(self):
        gw, sdk = self._gateway()
        pagamento_mp = {
            "id": 99,
            "status": "approved",
            "status_detail": "accredited",
            "external_reference": "10",
            "transaction_amount": 221.0,
            "payment_method_id": "pix",
        }
        sdk.payment.return_value.get.return_value = {
            "status": 200,
            "response": pagamento_mp,
        }
        info = gw.get_payment("99")
        assert (info.payment_id, info.status, info.method) == ("99", "approved", "pix")
        assert info.amount == Decimal("221.0")

        sdk.refund.return_value.create.return_value = {
            "status": 201,
            "response": {"id": 7},
        }
        assert gw.refund("99").refund_id == "7"
        sdk.refund.return_value.create.assert_called_once_with("99")

        sdk.payment.return_value.search.return_value = {
            "status": 200,
            "response": {"results": [pagamento_mp]},
        }
        assert gw.find_payment_by_reference("10").payment_id == "99"
        sdk.payment.return_value.search.return_value = {
            "status": 200,
            "response": {"results": []},
        }
        assert gw.find_payment_by_reference("10") is None

    def test_sem_token_falha(self):
        with pytest.raises(PaymentGatewayError):
            MercadoPagoGateway(Settings(MP_ACCESS_TOKEN=None))

    def test_sdk_real_e_instanciado_com_token(self):
        gw = MercadoPagoGateway(Settings(MP_ACCESS_TOKEN="TEST-123"))
        assert gw.sdk is not None


class TestFakeGateway:
    def test_fluxo(self):
        gw = FakeGateway()
        assert gw.create_checkout(_request()).preference_id == "fake-pref-10"
        info = gw.simulate("10", "approved", Decimal("1"))
        assert gw.get_payment(info.payment_id).status == "approved"
        assert gw.find_payment_by_reference("10") is info
        assert gw.find_payment_by_reference("11") is None
        gw.refund(info.payment_id)
        assert info.status == "refunded"
        with pytest.raises(PaymentGatewayError):
            gw.get_payment("nao-existe")


def test_fabrica_de_gateway(monkeypatch):
    from app.config import get_settings

    set_gateway(None)
    assert get_gateway().name == "fake"
    set_gateway(None)
    monkeypatch.setattr(get_settings(), "PAYMENT_GATEWAY", "mercadopago")
    monkeypatch.setattr(get_settings(), "MP_ACCESS_TOKEN", "TEST-abc")
    assert get_gateway().name == "mercadopago"
    set_gateway(None)
