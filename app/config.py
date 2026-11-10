from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Banco relacional (billing_db) ────────────
    DB_USER: str = "billing_service"
    DB_PASSWORD: str = "billing_service"
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    DB_NAME: str = "billing_db"

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # ── Autenticação (JWT emitido pela Lambda/OS Service) ──
    JWT_SECRET_KEY: str = "default-secret-key-change-in-production-12345"
    JWT_ALGORITHM: str = "HS256"

    # ── Aplicação ────────────────────────────────
    APP_ENV: str = "development"
    SERVICE_NAME: str = "billing-service"
    ORCAMENTO_VALIDADE_HORAS: int = 48

    # ── Pagamentos ───────────────────────────────
    # fake: sem credenciais (dev/testes) | mercadopago: sandbox/produção
    PAYMENT_GATEWAY: str = "fake"
    MP_ACCESS_TOKEN: str | None = None
    # "Assinatura secreta" da aplicação no painel do MP (valida x-signature)
    MP_WEBHOOK_SECRET: str | None = None
    # URL pública do webhook (API Gateway): https://<api>/api/v1/pagamentos/webhook
    MP_NOTIFICATION_URL: str | None = None
    MP_USE_SANDBOX_URL: bool = True
    PAYMENT_EXPIRATION_MINUTES: int = 30
    PAYMENT_RECONCILE_INTERVAL_SECONDS: float = 60.0

    # ── Mensageria (Amazon SQS) ──────────────────
    AWS_REGION: str = "sa-east-1"
    AWS_ENDPOINT_URL: str | None = None
    SQS_QUEUE_PREFIX: str = "fiap-officine"
    SQS_WAIT_TIME_SECONDS: int = 20
    SQS_MAX_MESSAGES: int = 10
    RUN_WORKERS: bool = False
    OUTBOX_RELAY_INTERVAL_SECONDS: float = 1.0

    # ── Observabilidade ──────────────────────────
    NEW_RELIC_LICENSE_KEY: str | None = None
    NEW_RELIC_APP_NAME: str = "officine-billing-service"
    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}

    def queue_name(self, logical_name: str) -> str:
        if not self.SQS_QUEUE_PREFIX:
            return logical_name
        return f"{self.SQS_QUEUE_PREFIX}-{logical_name}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
