import os
from collections.abc import Generator

os.environ["RDP_SESSION_DATABASE_URL"] = "sqlite:///./test-rdp-session.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Server, ServerCredential
from app.security import hash_agent_secret

TEST_DATABASE_URL = "sqlite:///./test-rdp-session.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def override_get_db() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def agent_identity() -> tuple[str, str]:
    server_id = "11111111-1111-1111-1111-111111111111"
    secret = "test-secret-with-high-entropy-placeholder"
    with TestingSessionLocal() as db:
        db.add(Server(id=server_id, enabled=True))
        db.add(ServerCredential(server_id=server_id, token_hash=hash_agent_secret(secret)))
        db.commit()
    return server_id, secret


@pytest.fixture
def agent_headers(agent_identity: tuple[str, str]) -> dict[str, str]:
    server_id, secret = agent_identity
    return {"X-Server-ID": server_id, "Authorization": f"Bearer {secret}"}
