"""API REST do Billing: orçamentos, pagamentos e webhook do Mercado Pago."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.domain.enums import StatusOrcamento, StatusPagamento
from app.payments.gateway import PaymentGatewayError
from app.payments.signature import sign
from tests.helpers import (
    orcamento_gerado,
    pagamento_solicitado,
    tipos_respondidos,
)

SECRET = "segredo-webhook-teste"


def _webhook(client, payment_id: str, secret: str = SECRET, tipo: str = "payment"):
    ts = "1704908010"
    request_id = "req-123"
    assinatura = sign(secret, payment_id, request_id, ts)
    return client.post(
        f"/api/v1/pagamentos/webhook?data.id={payment_id}&type={tipo}",
        json={"action": "payment.updated", "type": tipo, "data": {"id": payment_id}},
        headers={"x-signature": f"ts={ts},v1={assinatura}", "x-request-id": request_id},
    )


class TestOrcamentosAPI:
    def test_requer_autenticacao(self, client):
        assert client.get("/api/v1/orcamentos/").status_code == 401
        resp = client.get("/api/v1/orcamentos/", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 401

    def test_cliente_ve_apenas_os_proprios(
        self, client, db_session, cliente_headers, outro_cliente_headers, admin_headers
    ):
        orcamento = orcamento_gerado(db_session, os_id=1, cliente_id=7)
        orcamento_gerado(db_session, os_id=2, cliente_id=99)

        meus = client.get("/api/v1/orcamentos/", headers=cliente_headers).json()
        assert [o["id"] for o in meus] == [orcamento.id]
        todos = client.get("/api/v1/orcamentos/", headers=admin_headers).json()
        assert len(todos) == 2
        por_os = client.get("/api/v1/orcamentos/?os_id=1", headers=admin_headers).json()
        assert [o["os_id"] for o in por_os] == [1]

        assert (
            client.get(
                f"/api/v1/orcamentos/{orcamento.id}", headers=cliente_headers
            ).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/v1/orcamentos/{orcamento.id}", headers=outro_cliente_headers
            ).status_code
            == 403
        )
        assert (
            client.get("/api/v1/orcamentos/999", headers=admin_headers).status_code
            == 404
        )

    def test_cliente_aprova_e_evento_e_publicado(
        self, client, db_session, cliente_headers
    ):
        orcamento = orcamento_gerado(db_session)
        resp = client.post(
            f"/api/v1/orcamentos/{orcamento.id}/aprovar", headers=cliente_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "aprovado"
        assert resp.json()["decidido_em"] is not None
        assert tipos_respondidos(db_session)[-1] == "OrcamentoAprovado"
        # Decisão é única
        again = client.post(
            f"/api/v1/orcamentos/{orcamento.id}/aprovar", headers=cliente_headers
        )
        assert again.status_code == 409

    def test_outro_cliente_nao_aprova(self, client, db_session, outro_cliente_headers):
        orcamento = orcamento_gerado(db_session)
        resp = client.post(
            f"/api/v1/orcamentos/{orcamento.id}/aprovar", headers=outro_cliente_headers
        )
        assert resp.status_code == 403

    def test_recusar_com_motivo(self, client, db_session, cliente_headers):
        orcamento = orcamento_gerado(db_session)
        resp = client.post(
            f"/api/v1/orcamentos/{orcamento.id}/recusar",
            json={"motivo": "Muito caro"},
            headers=cliente_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "recusado"
        assert resp.json()["motivo"] == "Muito caro"
        assert tipos_respondidos(db_session)[-1] == "OrcamentoRecusado"

    def test_aprovar_inexistente_e_expirado(self, client, db_session, admin_headers):
        assert (
            client.post(
                "/api/v1/orcamentos/999/aprovar", headers=admin_headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/orcamentos/999/recusar", headers=admin_headers
            ).status_code
            == 404
        )
        orcamento = orcamento_gerado(db_session)
        orcamento.expira_em = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()
        resp = client.post(
            f"/api/v1/orcamentos/{orcamento.id}/aprovar", headers=admin_headers
        )
        assert resp.status_code == 410
        db_session.expire_all()
        assert orcamento.status == StatusOrcamento.EXPIRADO


class TestPagamentosAPI:
    def test_consultar_pagamento(
        self, client, db_session, admin_headers, cliente_headers, outro_cliente_headers
    ):
        orcamento, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        resp = client.get(f"/api/v1/pagamentos/{pagamento.id}", headers=cliente_headers)
        assert resp.status_code == 200
        assert resp.json()["checkout_url"]
        assert (
            client.get(
                f"/api/v1/pagamentos/{pagamento.id}", headers=outro_cliente_headers
            ).status_code
            == 403
        )
        assert (
            client.get("/api/v1/pagamentos/999", headers=admin_headers).status_code
            == 404
        )
        lista = client.get(
            f"/api/v1/pagamentos/?orcamento_id={orcamento.id}", headers=admin_headers
        )
        assert [p["id"] for p in lista.json()] == [pagamento.id]
        assert (
            client.get(
                "/api/v1/pagamentos/?orcamento_id=999", headers=admin_headers
            ).status_code
            == 404
        )

    def test_simular_aprovado_publica_confirmacao(
        self, client, db_session, admin_headers
    ):
        _, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        resp = client.post(
            f"/api/v1/pagamentos/{pagamento.id}/simular",
            json={"status": "approved"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "aprovado"
        assert resp.json()["mp_payment_id"]
        assert tipos_respondidos(db_session)[-1] == "PagamentoConfirmado"

    def test_simular_recusado_publica_recusa(self, client, db_session, admin_headers):
        _, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        resp = client.post(
            f"/api/v1/pagamentos/{pagamento.id}/simular",
            json={"status": "rejected"},
            headers=admin_headers,
        )
        assert resp.json()["status"] == "recusado"
        assert tipos_respondidos(db_session)[-1] == "PagamentoRecusado"

    def test_simular_inexistente(self, client, admin_headers):
        assert (
            client.post(
                "/api/v1/pagamentos/999/simular", headers=admin_headers
            ).status_code
            == 404
        )


class TestWebhookMercadoPago:
    def test_assinatura_invalida_retorna_401(self, client):
        resp = _webhook(client, "123", secret="outro-segredo")
        assert resp.status_code == 401
        sem_header = client.post(
            "/api/v1/pagamentos/webhook?data.id=1&type=payment", json={}
        )
        assert sem_header.status_code == 401

    def test_tipo_nao_pagamento_e_ignorado(self, client):
        resp = _webhook(client, "123", tipo="merchant_order")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignorado"

    def test_pagamento_aprovado_confirma(
        self, client, db_session, admin_headers, gateway
    ):
        _, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        info = gateway.simulate(str(pagamento.id), "approved", pagamento.valor, "visa")
        resp = _webhook(client, info.payment_id)
        assert resp.status_code == 200
        assert resp.json()["situacao"] == "aprovado"
        db_session.expire_all()
        assert pagamento.metodo == "visa"
        assert tipos_respondidos(db_session)[-1] == "PagamentoConfirmado"
        # Notificação repetida não publica de novo
        _webhook(client, info.payment_id)
        assert tipos_respondidos(db_session).count("PagamentoConfirmado") == 1

    def test_pagamento_pendente_nao_muda_nada(
        self, client, db_session, admin_headers, gateway
    ):
        _, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        info = gateway.simulate(str(pagamento.id), "in_process", pagamento.valor)
        _webhook(client, info.payment_id)
        db_session.expire_all()
        assert pagamento.status == StatusPagamento.PENDENTE

    def test_pagamento_tardio_de_orcamento_cancelado_e_estornado(
        self, client, db_session, admin_headers, gateway
    ):
        from tests.helpers import processar

        orcamento, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        processar(db_session, "CancelarOrcamento", {"orcamento_id": orcamento.id})
        info = gateway.simulate(str(pagamento.id), "approved", pagamento.valor)
        _webhook(client, info.payment_id)
        db_session.expire_all()
        assert pagamento.status == StatusPagamento.ESTORNADO
        assert gateway.refunds == [info.payment_id]
        assert "PagamentoConfirmado" not in tipos_respondidos(db_session)

    def test_referencia_desconhecida(self, client, gateway):
        info = gateway.simulate("9999", "approved", 10)
        assert _webhook(client, info.payment_id).json()["pagamento_id"] is None
        info = gateway.simulate("nao-numerico", "approved", 10)
        assert _webhook(client, info.payment_id).json()["pagamento_id"] is None

    def test_estorno_externo_atualiza_status(
        self, client, db_session, admin_headers, gateway
    ):
        _, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        info = gateway.simulate(str(pagamento.id), "refunded", pagamento.valor)
        _webhook(client, info.payment_id)
        db_session.expire_all()
        assert pagamento.status == StatusPagamento.ESTORNADO

    def test_falha_no_provedor_retorna_502(self, client):
        with patch("app.services.pagamento_service.get_gateway") as gw:
            gw.return_value.get_payment.side_effect = PaymentGatewayError("timeout")
            assert _webhook(client, "555").status_code == 502


def test_health(client):
    resp = client.get("/billing/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["services"]["database"]["status"] == "up"
    assert data["services"]["messaging"]["status"] == "up"
    assert data["services"]["payment_gateway"]["provider"] == "fake"
    assert client.get("/").json()["service"] == "billing-service"


def test_health_banco_fora(client):
    from unittest.mock import MagicMock

    from app.infrastructure.database import get_db
    from app.main import app

    def db_quebrado():
        db = MagicMock()
        db.execute.side_effect = Exception("db down")
        yield db

    app.dependency_overrides[get_db] = db_quebrado
    with patch("app.api.v1.health.get_bus") as bus:
        bus.return_value.ping.side_effect = Exception("sqs down")
        resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["services"]["messaging"]["status"] == "down"
