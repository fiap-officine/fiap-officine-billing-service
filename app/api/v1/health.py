import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.entities.messaging import OutboxMessage
from app.infrastructure.database import get_db
from app.messaging.sqs import get_bus
from app.services.messages import BILLING_COMMANDS

router = APIRouter(tags=["Health"])
START_TIME = time.time()


@router.get("/health", include_in_schema=False)
@router.get("/billing/health", summary="Healthcheck do Billing Service")
def get_health(response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    services: dict = {}
    healthy = True
    try:
        db.execute(text("SELECT 1"))
        services["database"] = {"status": "up", "type": "PostgreSQL"}
        services["outbox"] = {
            "pending": db.scalar(
                select(func.count())
                .select_from(OutboxMessage)
                .where(OutboxMessage.status == "pending")
            )
            or 0
        }
    except Exception as exc:
        healthy = False
        services["database"] = {"status": "down", "error": str(exc)[:200]}
    try:
        get_bus().ping(BILLING_COMMANDS)
        services["messaging"] = {"status": "up", "type": "SQS"}
    except Exception as exc:
        services["messaging"] = {"status": "down", "error": str(exc)[:200]}
    services["payment_gateway"] = {"provider": settings.PAYMENT_GATEWAY}

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "healthy" if healthy else "unhealthy",
        "service": settings.SERVICE_NAME,
        "environment": settings.APP_ENV,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(time.time() - START_TIME, 2),
        "services": services,
    }
