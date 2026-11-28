import threading
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import get_settings
from .mailer import flush_email_queue

_MAX_POOL_SIZE = 8
_pool_lock = threading.Lock()
_pool = []
_pool_dsn = None


def _connect(dsn):
    return psycopg.connect(
        dsn,
        row_factory=dict_row,
        prepare_threshold=None,
        connect_timeout=10,
    )


def _acquire_connection():
    global _pool_dsn
    dsn = get_settings().database_url
    with _pool_lock:
        if _pool_dsn != dsn:
            while _pool:
                try:
                    _pool.pop().close()
                except Exception:
                    pass
            _pool_dsn = dsn
        while _pool:
            conn = _pool.pop()
            if not getattr(conn, "closed", True) and not getattr(conn, "broken", False):
                try:
                    conn.execute("select 1")
                    conn.rollback()
                    return conn
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
    return _connect(dsn)


def _release_connection(conn):
    if getattr(conn, "closed", True) or getattr(conn, "broken", False):
        try:
            conn.close()
        except Exception:
            pass
        return
    with _pool_lock:
        if len(_pool) < _MAX_POOL_SIZE:
            _pool.append(conn)
            return
    try:
        conn.close()
    except Exception:
        pass


@contextmanager
def transaction():
    conn = _acquire_connection()
    try:
        yield conn
        conn.commit()
    except BaseException:
        try:
            conn.rollback()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
        raise
    finally:
        _release_connection(conn)
    flush_email_queue()
