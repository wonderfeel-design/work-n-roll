import os
import uuid

import psycopg
import pytest
from psycopg import sql

from app import db


def pytest_configure(config):
    config.addinivalue_line("markers", "gemma: calls the Gemini API (slow, uses quota)")
    config.addinivalue_line("markers", "elevenlabs: calls ElevenLabs (uses credits)")


@pytest.fixture(autouse=True)
def pg_schema():
    """Every test gets its own empty PostgreSQL schema, dropped afterwards. Real data is never touched.

    Uses TEST_DATABASE_URL, else DATABASE_URL (start it with: docker compose up -d postgres).
    """
    url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or db.DATABASE_URL
    schema = f"test_{uuid.uuid4().hex[:12]}"
    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not reachable ({e.__class__.__name__}): docker compose up -d postgres")
    db.use(url, schema)
    db.init_db()
    yield schema
    db.use(url, "public")
    with psycopg.connect(url) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
