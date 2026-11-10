"""Validação da assinatura dos webhooks do Mercado Pago (header `x-signature`).

Header: ``x-signature: ts=1704908010,v1=618c8534...``
Manifest assinado (HMAC-SHA256 com a "assinatura secreta" da aplicação):
``id:<data.id>;request-id:<x-request-id>;ts:<ts>;``
Partes ausentes são omitidas; `data.id` alfanumérico vai em minúsculas.
"""

import hashlib
import hmac


def parse_signature(header: str | None) -> tuple[str | None, str | None]:
    if not header:
        return None, None
    parts: dict[str, str] = {}
    for chunk in header.split(","):
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            parts[key.strip()] = value.strip()
    return parts.get("ts"), parts.get("v1")


def build_manifest(data_id: str | None, request_id: str | None, ts: str | None) -> str:
    manifest = ""
    if data_id:
        manifest += f"id:{data_id.lower() if data_id.isalnum() else data_id};"
    if request_id:
        manifest += f"request-id:{request_id};"
    if ts:
        manifest += f"ts:{ts};"
    return manifest


def sign(secret: str, data_id: str | None, request_id: str | None, ts: str) -> str:
    manifest = build_manifest(data_id, request_id, ts)
    return hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()


def is_valid_signature(
    secret: str,
    x_signature: str | None,
    x_request_id: str | None,
    data_id: str | None,
) -> bool:
    ts, v1 = parse_signature(x_signature)
    if not ts or not v1:
        return False
    expected = sign(secret, data_id, x_request_id, ts)
    return hmac.compare_digest(expected, v1)
