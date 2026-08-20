import hashlib
import hmac

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Server, ServerCredential
from app.timeutils import utc_now


def hash_agent_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def authenticate_agent(
    authorization: str | None = Header(default=None, alias="Authorization"),
    server_id: str | None = Header(default=None, alias="X-Server-ID"),
    db: Session = Depends(get_db),
) -> Server:
    if not authorization or not authorization.startswith("Bearer ") or not server_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="agent authentication required")

    secret = authorization[7:].strip()
    if not secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="agent authentication required")

    server = db.get(Server, server_id)
    if server is None or not server.enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid agent credentials")

    supplied_hash = hash_agent_secret(secret)
    credentials = db.scalars(
        select(ServerCredential).where(
            ServerCredential.server_id == server.id,
            ServerCredential.revoked_at.is_(None),
        )
    ).all()

    matched = next(
        (credential for credential in credentials if hmac.compare_digest(credential.token_hash, supplied_hash)),
        None,
    )
    if matched is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid agent credentials")

    matched.last_used_at = utc_now()
    db.commit()
    return server


def authenticate_query_api(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    configured_key = get_settings().query_api_key
    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="query API is not configured",
        )
    if not x_api_key or not hmac.compare_digest(configured_key, x_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")
