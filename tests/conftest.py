import os

os.environ["NEW_RELIC_LICENSE_KEY"] = ""
os.environ["RUN_WORKERS"] = "false"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "sa-east-1"
os.environ["AWS_REGION"] = "sa-east-1"
os.environ.pop("AWS_ENDPOINT_URL", None)
os.environ["SQS_WAIT_TIME_SECONDS"] = "0"
os.environ["PAYMENT_GATEWAY"] = "fake"
os.environ["MP_WEBHOOK_SECRET"] = "segredo-webhook-teste"
os.environ["JWT_SECRET_KEY"] = "segredo-jwt-teste"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from jose import jwt  # noqa: E402
from moto import mock_aws  # noqa: E402
from sqlalchemy import StaticPool, create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.domain.entities  # noqa: E402,F401
from app.config import get_settings  # noqa: E402
from app.infrastructure.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.messaging.sqs import SqsBus, set_bus  # noqa: E402
from app.payments import set_gateway  # noqa: E402
from app.payments.fake_gateway import FakeGateway  # noqa: E402
from app.services.messages import BILLING_COMMANDS, OS_REPLIES  # noqa: E402

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def drain_queue(bus: SqsBus, logical: str) -> list[dict]:
    drained = []
    while True:
        msgs = bus.receive(logical, wait_seconds=0, max_messages=10)
        if not msgs:
            return drained
        for msg in msgs:
            bus.delete(logical, msg["ReceiptHandle"])
        drained.extend(msgs)


@pytest.fixture(scope="session")
def _aws_session():
    settings = get_settings()
    with mock_aws():
        bus = SqsBus(settings)
        for logical in (BILLING_COMMANDS, OS_REPLIES):
            bus.client.create_queue(QueueName=settings.queue_name(logical))
        yield bus


@pytest.fixture(autouse=True)
def sqs_bus(_aws_session):
    for logical in (BILLING_COMMANDS, OS_REPLIES):
        drain_queue(_aws_session, logical)
    set_bus(_aws_session)
    yield _aws_session
    set_bus(None)


@pytest.fixture(autouse=True)
def gateway():
    fake = FakeGateway()
    set_gateway(fake)
    yield fake
    set_gateway(None)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def session_factory(db_session):
    return TestingSessionLocal


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_token(role: str = "admin", sub: str = "operador", cliente_id=None) -> str:
    claims = {"sub": sub, "role": role}
    if cliente_id is not None:
        claims["cliente_id"] = cliente_id
    return jwt.encode(claims, os.environ["JWT_SECRET_KEY"], algorithm="HS256")


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {make_token()}"}


@pytest.fixture
def cliente_headers():
    # Token no formato emitido pela Lambda (cliente_id como string)
    token = make_token("cliente", "52998224725", "7")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def outro_cliente_headers():
    return {"Authorization": f"Bearer {make_token('cliente', '11144477735', 99)}"}
