"""Comandos da saga consumidos pelo Billing (billing-commands)."""

import pytest

from app.domain.enums import StatusOrcamento, StatusPagamento
from app.payments.gateway import PaymentGatewayError
from tests.helpers import (
    SAGA_ID,
    orcamento_aprovado,
    orcamento_gerado,
    pagamento_solicitado,
    payload_gerar,
    processar,
    respostas,
    tipos_respondidos,
)


class TestGerarOrcamento:
    def test_gera_orcamento_e_responde(self, db_session):
        orcamento = orcamento_gerado(db_session)
        assert orcamento.status == StatusOrcamento.GERADO
        assert str(orcamento.valor_total) == "221.00"
        assert len(orcamento.itens) == 2
        assert orcamento.saga_id == SAGA_ID
        resposta = respostas(db_session)[-1]
        assert resposta.message_type == "OrcamentoGerado"
        assert resposta.destination == "os-saga-replies"
        assert resposta.envelope["saga_id"] == SAGA_ID
        assert resposta.envelope["payload"]["orcamento_id"] == orcamento.id
        assert resposta.envelope["payload"]["valor_total"] == "221.00"

    def test_idempotente_por_os(self, db_session):
        primeiro = orcamento_gerado(db_session)
        processar(db_session, "GerarOrcamento", payload_gerar(), os_id=1)
        assert tipos_respondidos(db_session) == ["OrcamentoGerado", "OrcamentoGerado"]
        assert (
            respostas(db_session)[-1].envelope["payload"]["orcamento_id"] == primeiro.id
        )

    @pytest.mark.parametrize(
        "itens",
        [
            [],
            [{"tipo": "peca", "ref_id": 1, "quantidade": 1, "valor_unitario": "0"}],
            [{"tipo": "peca", "ref_id": 1, "quantidade": 1}],
            [{"tipo": "peca", "ref_id": 1, "quantidade": 1, "valor_unitario": "abc"}],
        ],
    )
    def test_itens_invalidos_geram_falha(self, db_session, itens):
        processar(db_session, "GerarOrcamento", payload_gerar(itens=itens))
        assert tipos_respondidos(db_session) == ["OrcamentoFalhou"]


class TestSolicitarPagamento:
    def test_cria_cobranca_e_responde_link(self, db_session, client, admin_headers):
        orcamento, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        assert pagamento.status == StatusPagamento.PENDENTE
        assert pagamento.valor == orcamento.valor_total
        assert pagamento.gateway == "fake"
        assert pagamento.mp_preference_id == f"fake-pref-{pagamento.id}"
        resposta = respostas(db_session)[-1]
        assert resposta.message_type == "PagamentoSolicitado"
        assert resposta.envelope["payload"]["pagamento_id"] == pagamento.id
        assert resposta.envelope["payload"]["checkout_url"]

    def test_idempotente(self, db_session, client, admin_headers):
        orcamento, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        processar(db_session, "SolicitarPagamento", {"orcamento_id": orcamento.id})
        assert len(orcamento.pagamentos) == 1
        assert (
            respostas(db_session)[-1].envelope["payload"]["pagamento_id"]
            == pagamento.id
        )

    def test_orcamento_nao_aprovado_recusa(self, db_session):
        orcamento = orcamento_gerado(db_session)
        processar(db_session, "SolicitarPagamento", {"orcamento_id": orcamento.id})
        assert tipos_respondidos(db_session)[-1] == "PagamentoRecusado"

    def test_localiza_orcamento_por_os(self, db_session, client, admin_headers):
        orcamento_aprovado(db_session, client, admin_headers, os_id=5)
        processar(db_session, "SolicitarPagamento", {}, os_id=5)
        assert tipos_respondidos(db_session)[-1] == "PagamentoSolicitado"


class TestCancelarOrcamento:
    def test_cancela_orcamento_e_cobranca_pendente(
        self, db_session, client, admin_headers
    ):
        orcamento, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        processar(
            db_session,
            "CancelarOrcamento",
            {"orcamento_id": orcamento.id, "motivo": "timeout"},
        )
        assert orcamento.status == StatusOrcamento.CANCELADO
        assert orcamento.motivo == "timeout"
        assert pagamento.status == StatusPagamento.CANCELADO
        assert tipos_respondidos(db_session)[-1] == "OrcamentoCancelado"

    def test_mantem_recusado(self, db_session, client, admin_headers):
        orcamento = orcamento_gerado(db_session)
        client.post(f"/api/v1/orcamentos/{orcamento.id}/recusar", headers=admin_headers)
        processar(db_session, "CancelarOrcamento", {"orcamento_id": orcamento.id})
        db_session.expire_all()
        assert orcamento.status == StatusOrcamento.RECUSADO

    def test_orcamento_inexistente_responde_mesmo_assim(self, db_session):
        processar(db_session, "CancelarOrcamento", {"orcamento_id": None}, os_id=404)
        resposta = respostas(db_session)[-1]
        assert resposta.message_type == "OrcamentoCancelado"
        assert resposta.envelope["payload"]["orcamento_id"] is None


class TestEstornarPagamento:
    def test_estorna_pagamento_aprovado(
        self, db_session, client, admin_headers, gateway
    ):
        orcamento, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        client.post(f"/api/v1/pagamentos/{pagamento.id}/simular", headers=admin_headers)
        processar(db_session, "EstornarPagamento", {"pagamento_id": pagamento.id})
        db_session.expire_all()
        assert pagamento.status == StatusPagamento.ESTORNADO
        assert pagamento.mp_refund_id.startswith("fake-refund-")
        assert gateway.refunds == [pagamento.mp_payment_id]
        payload = respostas(db_session)[-1].envelope["payload"]
        assert payload["estorno_necessario"] is True

    def test_localiza_pagamento_aprovado_pelo_orcamento(
        self, db_session, client, admin_headers
    ):
        orcamento, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        client.post(f"/api/v1/pagamentos/{pagamento.id}/simular", headers=admin_headers)
        processar(db_session, "EstornarPagamento", {"orcamento_id": orcamento.id})
        db_session.expire_all()
        assert pagamento.status == StatusPagamento.ESTORNADO

    def test_sem_pagamento_aprovado_e_noop(
        self, db_session, client, admin_headers, gateway
    ):
        orcamento, _ = pagamento_solicitado(db_session, client, admin_headers)
        processar(db_session, "EstornarPagamento", {"orcamento_id": orcamento.id})
        payload = respostas(db_session)[-1].envelope["payload"]
        assert payload["estorno_necessario"] is False
        assert gateway.refunds == []

    def test_falha_no_provedor_propaga_para_retry(
        self, db_session, client, admin_headers, gateway
    ):
        _, pagamento = pagamento_solicitado(db_session, client, admin_headers)
        client.post(f"/api/v1/pagamentos/{pagamento.id}/simular", headers=admin_headers)
        gateway.fail_next_refund = True
        with pytest.raises(PaymentGatewayError):
            processar(db_session, "EstornarPagamento", {"pagamento_id": pagamento.id})
        db_session.expire_all()
        assert pagamento.status == StatusPagamento.APROVADO


def test_comando_desconhecido_e_ignorado(db_session):
    assert processar(db_session, "ComandoQueNaoExiste", {}) == "processed"
    assert tipos_respondidos(db_session) == []
