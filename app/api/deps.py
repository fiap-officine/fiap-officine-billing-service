"""Autenticação: JWT emitido pela Lambda (clientes, via CPF) ou pelo OS Service
(operadores/admin). O Billing não acessa a base de clientes: confia nas claims
assinadas com o segredo compartilhado (o API Gateway também valida o token)."""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import get_settings
from app.domain.entities.billing import Orcamento

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class Principal(BaseModel):
    sub: str
    role: str
    cliente_id: int | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_principal(token: str = Depends(oauth2_scheme)) -> Principal:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token inválido")
    cliente_id = payload.get("cliente_id")
    return Principal(
        sub=str(sub),
        role=str(payload.get("role", "admin")),
        cliente_id=int(cliente_id) if cliente_id not in (None, "") else None,
    )


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Permissão de operador necessária")
    return principal


def ensure_owner(principal: Principal, orcamento: Orcamento) -> None:
    """Cliente só acessa o próprio orçamento; operador acessa todos."""
    if principal.is_admin:
        return
    if principal.cliente_id is None or principal.cliente_id != orcamento.cliente_id:
        raise HTTPException(
            status_code=403, detail="Este orçamento pertence a outro cliente"
        )
