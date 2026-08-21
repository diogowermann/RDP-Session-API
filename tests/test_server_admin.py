from sqlalchemy import select

from app.models import ServerCredential
from app.security import hash_agent_secret
from app.services.server_admin import register_server, rotate_server_secret
from tests.conftest import TestingSessionLocal


def test_register_and_rotate_server_secret():
    with TestingSessionLocal() as db:
        server, first_secret = register_server(db, hostname="SRV-RDS01")
        server_id = server.id
        first_hash = hash_agent_secret(first_secret)

        assert db.scalar(
            select(ServerCredential).where(ServerCredential.token_hash == first_hash)
        ) is not None

        second_secret = rotate_server_secret(db, server_id)
        credentials = db.scalars(
            select(ServerCredential).where(ServerCredential.server_id == server_id)
        ).all()

        assert second_secret != first_secret
        assert len(credentials) == 2
        assert sum(credential.revoked_at is None for credential in credentials) == 1
        assert any(credential.token_hash == hash_agent_secret(second_secret) for credential in credentials)
