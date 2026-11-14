import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.domain.enums import StatusPagamento
from app.messaging.envelope import new_envelope
from app.services import pagamento_service
from app.services.messages import BILLING_COMMANDS, OS_REPLIES
from app.workers import (
    BackgroundWorkers,
    run_consumer_once,
    run_outbox_relay_once,
    run_reconciler_once,
)
from tests.conftest import drain_queue
from tests.helpers import pagamento_solicitado, payload_gerar


def test_consumer_e_relay_ponta_a_ponta(db_session, session_factory, sqs_bus):
    """Comando chega pela fila, é processado e a resposta sai pela os-saga-replies."""
    env = new_envelope(
        "GerarOrcamento",
        "command",
        payload_gerar(),
        source="os-service",
        saga_id="saga-1",
        os_id=42,
    )
    sqs_bus.send(BILLING_COMMANDS, env.model_dump_json(), {"type": env.type})
    assert run_consumer_once(session_factory, sqs_bus, wait_seconds=0) == 1
    assert run_outbox_relay_once(session_factory, sqs_bus) == 1
    respostas = [json.loads(m["Body"]) for m in drain_queue(sqs_bus, OS_REPLIES)]
    assert [r["type"] for r in respostas] == ["OrcamentoGerado"]
    assert respostas[0]["saga_id"] == "saga-1" and respostas[0]["os_id"] == 42
    assert respostas[0]["source"] == "billing-service"


def test_reconciliador_aplica_pagamento_sem_webhook(
    db_session, session_factory, client, admin_headers, gateway
):
    _, pagamento = pagamento_solicitado(db_session, client, admin_headers)
    pagamento.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()
    assert run_reconciler_once(session_factory) == 0  # nada no provedor ainda
    gateway.simulate(str(pagamento.id), "approved", pagamento.valor)
    assert run_reconciler_once(session_factory) == 1
    db_session.expire_all()
    assert pagamento.status == StatusPagamento.APROVADO


def test_simular_exige_gateway_fake(db_session, client, admin_headers):
    from app.payments import set_gateway

    _, pagamento = pagamento_solicitado(db_session, client, admin_headers)
    mp = MagicMock()
    mp.name = "mercadopago"
    set_gateway(mp)
    resp = client.post(
        f"/api/v1/pagamentos/{pagamento.id}/simular", headers=admin_headers
    )
    assert resp.status_code == 400


def test_background_workers_incluem_reconciliador_com_mercadopago():
    workers = BackgroundWorkers(Settings(PAYMENT_GATEWAY="mercadopago"))
    with (
        patch("app.workers.run_consumer_once", side_effect=RuntimeError("x")),
        patch("app.workers.run_outbox_relay_once", return_value=0),
        patch("app.workers.run_reconciler_once", return_value=0),
    ):
        workers.start()
        assert {t.name for t in workers._threads} == {
            "billing-consumer",
            "outbox-relay",
            "payment-reconciler",
        }
        workers.stop(timeout=5)
    assert workers._threads == []


def test_processar_pagamento_recusado_depois_de_aprovado_e_ignorado(
    db_session, client, admin_headers, gateway
):
    _, pagamento = pagamento_solicitado(db_session, client, admin_headers)
    aprovado = gateway.simulate(str(pagamento.id), "approved", pagamento.valor)
    pagamento_service.processar_pagamento(db_session, aprovado)
    recusado = gateway.simulate(str(pagamento.id), "rejected", pagamento.valor)
    pagamento_service.processar_pagamento(db_session, recusado)
    assert pagamento.status == StatusPagamento.APROVADO
