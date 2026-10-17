"""FalkorDB connection handling.

Uses the official `falkordb` Python client (verified against falkordb==1.8.0):
    FalkorDB(host, port, password, socket_timeout, socket_connect_timeout)
    db.select_graph(name) -> Graph
    graph.query(q, params, timeout) / graph.ro_query(q, params, timeout) -> QueryResult
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from falkordb import FalkorDB
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.config import Settings, get_settings

log = logging.getLogger("shelfsense.db")


class DatabaseUnavailable(RuntimeError):
    """FalkorDB could not be reached. Message is safe to show to users."""


class QueryFailed(RuntimeError):
    """A query was rejected or timed out. Message is safe to show to users."""


class GraphMissing(QueryFailed):
    """The graph key does not exist yet (never seeded)."""


@dataclass
class QueryOutcome:
    rows: list[list[Any]]
    header: list[str]
    duration_ms: float


class GraphClient:
    """Thin wrapper that adds timeouts, safe errors and timing around FalkorDB."""

    def __init__(self, settings: Settings | None = None, graph_name: str | None = None):
        self.settings = settings or get_settings()
        self.graph_name = graph_name or self.settings.graph_name
        self._db: FalkorDB | None = None
        self._graph = None

    def _connect(self):
        if self._graph is None:
            self._db = FalkorDB(
                host=self.settings.falkordb_host,
                port=self.settings.falkordb_port,
                password=self.settings.falkordb_password,
                socket_timeout=5,
                socket_connect_timeout=2,
            )
            self._graph = self._db.select_graph(self.graph_name)
        return self._graph

    def ping(self) -> bool:
        try:
            self._connect()
            return bool(self._db.connection.ping())
        except (RedisError, OSError) as exc:
            log.warning("FalkorDB ping failed: %s", type(exc).__name__)
            self._graph = None
            return False

    def _run(self, cypher: str, params: dict | None, read_only: bool) -> QueryOutcome:
        try:
            graph = self._connect()
            start = time.perf_counter()
            fn = graph.ro_query if read_only else graph.query
            result = fn(cypher, params or {}, timeout=self.settings.query_timeout_ms)
            duration = (time.perf_counter() - start) * 1000
        except (RedisConnectionError, RedisTimeoutError, OSError) as exc:
            self._graph = None
            raise DatabaseUnavailable(
                f"FalkorDB is not reachable at {self.settings.falkordb_host}:"
                f"{self.settings.falkordb_port}. Start it with `docker compose up -d falkordb`."
            ) from exc
        except RedisError as exc:
            if "empty key" in str(exc).lower():
                raise GraphMissing("The demo graph has not been seeded yet. Run `python -m scripts.reset_demo`.") from exc
            # Query errors (syntax, timeout inside the engine). Log detail, return safe text.
            log.error("FalkorDB query error: %s", exc)
            raise QueryFailed("The graph query could not be completed.") from exc
        header = [h[1] if isinstance(h, (list, tuple)) else str(h) for h in (result.header or [])]
        return QueryOutcome(rows=list(result.result_set or []), header=header, duration_ms=round(duration, 2))

    def read(self, cypher: str, params: dict | None = None) -> QueryOutcome:
        return self._run(cypher, params, read_only=True)

    def write(self, cypher: str, params: dict | None = None) -> QueryOutcome:
        return self._run(cypher, params, read_only=False)

    def delete_graph(self) -> None:
        try:
            self._connect().delete()
        except RedisError as exc:
            # Deleting a graph that does not exist yet is fine.
            if "empty key" not in str(exc).lower() and "invalid graph" not in str(exc).lower():
                if isinstance(exc, (RedisConnectionError, RedisTimeoutError)):
                    raise DatabaseUnavailable("FalkorDB is not reachable.") from exc


_client: GraphClient | None = None


def get_client() -> GraphClient:
    global _client
    if _client is None:
        _client = GraphClient()
    return _client


def set_client(client: GraphClient | None) -> None:
    """Used by tests to inject a client bound to a test graph."""
    global _client
    _client = client
