from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import get_settings
from .mailer import flush_email_queue


@contextmanager
def transaction():
    conn = psycopg.connect(
        get_settings().database_url,
        row_factory=dict_row,
        prepare_threshold=None,
        connect_timeout=10,
    )
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    flush_email_queue()
