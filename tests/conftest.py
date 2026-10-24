import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import create_app


@pytest.fixture
def app():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is required: tests intentionally use real PostgreSQL.")
    schema = "test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    application = create_app(url, demo=True, schema=schema)
    with TestClient(application):
        yield application
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture
def clients(app):
    result = []
    for name in ("anna", "max", "maria"):
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"email": f"{name}@example.test", "password": "ClubDemo2026!"})
        assert response.status_code == 200
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        result.append(client)
    yield result
    for client in result:
        client.close()
