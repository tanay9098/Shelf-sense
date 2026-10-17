"""Shared fixtures.

Unit tests use no database. Integration tests run against a real FalkorDB, on a
separate graph (`shelfsense_test`) so the demo graph is never touched. If FalkorDB is
not reachable they are SKIPPED (never silently mocked).
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import connection
from app.db.connection import GraphClient
from app.db.seed import reset_graph

TEST_GRAPH = os.getenv("FALKORDB_TEST_GRAPH", "shelfsense_test")


@pytest.fixture(scope="session")
def graph_client():
    client = GraphClient(graph_name=TEST_GRAPH)
    if not client.ping():
        s = get_settings()
        pytest.skip(f"FalkorDB not reachable at {s.falkordb_host}:{s.falkordb_port} - integration tests skipped")
    yield client
    client.delete_graph()


@pytest.fixture
def seeded(graph_client):
    """Fresh deterministic dataset for every test, so scenarios cannot leak into each other."""
    reset_graph(graph_client)
    return graph_client


@pytest.fixture
def api(seeded):
    connection.set_client(seeded)
    from app.main import app
    with TestClient(app) as c:
        yield c
    connection.set_client(None)


@pytest.fixture
def api_db_down():
    """API wired to a port where nothing listens - exercises failure handling without mocks."""
    base = get_settings()
    bad = Settings(**{**base.__dict__, "falkordb_host": "127.0.0.1", "falkordb_port": 1})
    connection.set_client(GraphClient(settings=bad, graph_name="unreachable"))
    from app.main import app
    with TestClient(app) as c:
        yield c
    connection.set_client(None)
