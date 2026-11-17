import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import health, orcamentos, pagamentos
from app.config import get_settings
from app.core.logging import setup_json_logging
from app.core.middleware import ObservabilityMiddleware

settings = get_settings()
setup_json_logging(
    service_name=settings.NEW_RELIC_APP_NAME,
    environment=settings.APP_ENV,
    log_level=settings.LOG_LEVEL,
)
logger = logging.getLogger("app.main")

if settings.NEW_RELIC_LICENSE_KEY or os.getenv("NEW_RELIC_LICENSE_KEY"):
    try:  # pragma: no cover - depende do agente
        import newrelic.agent

        os.environ.setdefault("NEW_RELIC_APP_NAME", settings.NEW_RELIC_APP_NAME)
        os.environ.setdefault("NEW_RELIC_DISTRIBUTED_TRACING_ENABLED", "true")
        newrelic.agent.initialize()
        logger.info("Agente APM New Relic inicializado.")
    except Exception as exc:  # pragma: no cover
        logger.warning("Não foi possível inicializar o New Relic: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    workers = None
    if settings.RUN_WORKERS:
        from app.workers import BackgroundWorkers

        workers = BackgroundWorkers(settings)
        workers.start()
        logger.info("Workers do Billing iniciados no processo da API")
    yield
    if workers is not None:
        workers.stop()


app = FastAPI(
    title="Oficina Mecânica - Billing Service",
    description=(
        "Orçamentos, aprovação pelo cliente e pagamentos via **Mercado Pago** "
        "(Checkout Pro, webhook com validação de `x-signature`, estorno como "
        "compensação). Participante da saga orquestrada pelo OS Service."
    ),
    version="1.0.0",
    docs_url="/billing/docs",
    redoc_url="/billing/redoc",
    openapi_url="/billing/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(ObservabilityMiddleware)

app.include_router(health.router)
app.include_router(orcamentos.router, prefix="/api/v1")
app.include_router(pagamentos.router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
def root():
    return {"status": "ok", "service": settings.SERVICE_NAME}
