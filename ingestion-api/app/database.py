from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg import Connection


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://agentops:agentops@localhost:5432/agentops",
)


# --- connection pooling -------------------------------------------------
#
# A module-level psycopg_pool.ConnectionPool reuses connections across
# requests instead of opening a fresh one per HTTP call. If
# psycopg_pool is not installed we fall back to a plain connect()/close()
# so the API still runs in a minimal dev environment.
_pool: Any = None


def _get_pool() -> Any:
    global _pool

    if _pool is None:
        try:
            from psycopg_pool import ConnectionPool

            _pool = ConnectionPool(
                DATABASE_URL,
                min_size=1,
                max_size=10,
                open=True,
            )
        except Exception:
            _pool = False

    return _pool


@contextmanager
def get_connection() -> Iterator[Connection]:
    """
    Yield a database connection.

    Used as `with get_connection() as connection:`. With a pool the
    connection is checked back in on exit (commit on success, rollback
    on exception). Without a pool a fresh connection is opened and
    closed each call, preserving the original MVP behaviour.
    """

    pool = _get_pool()

    if pool:
        with pool.connection() as connection:
            yield connection
        return

    connection = psycopg.connect(DATABASE_URL)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()