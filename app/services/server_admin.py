import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Server, ServerCredential
from app.security import hash_agent_secret
from app.timeutils import utc_now


def generate_agent_secret() -> str:
    return secrets.token_urlsafe(32)


def register_server(
    db: Session,
    *,
    hostname: str | None = None,
    fqdn: str | None = None,
    os_version: str | None = None,
) -> tuple[Server, str]:
    server = Server(hostname=hostname, fqdn=fqdn, os_version=os_version, enabled=True)
    secret = generate_agent_secret()
    db.add(server)
    db.flush()
    db.add(ServerCredential(server_id=server.id, token_hash=hash_agent_secret(secret)))
    db.commit()
    db.refresh(server)
    return server, secret


def rotate_server_secret(db: Session, server_id: str) -> str:
    server = db.get(Server, server_id)
    if server is None:
        raise ValueError("server not found")

    now = utc_now()
    credentials = db.scalars(
        select(ServerCredential).where(
            ServerCredential.server_id == server_id,
            ServerCredential.revoked_at.is_(None),
        )
    ).all()
    for credential in credentials:
        credential.revoked_at = now

    secret = generate_agent_secret()
    db.add(ServerCredential(server_id=server_id, token_hash=hash_agent_secret(secret)))
    db.commit()
    return secret
