"""
Claude Token Guard — layer database
Supporta SQLite (default) e Postgres.
"""
import sqlite3
import os
from config import DB_TYPE, DB_SQLITE_PATH, PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASS

# ── Connessione ───────────────────────────────────────────────────────────

def get_conn():
    if DB_TYPE == "postgres":
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, dbname=PG_DB,
            user=PG_USER, password=PG_PASS, connect_timeout=5
        )
        conn.autocommit = True
        return conn
    else:
        os.makedirs(os.path.dirname(DB_SQLITE_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def get_cursor(conn):
    if DB_TYPE == "postgres":
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()

def rows_as_dicts(cursor):
    if DB_TYPE == "postgres":
        return [dict(r) for r in cursor.fetchall()]
    return [dict(r) for r in cursor.fetchall()]

# ── Schema ────────────────────────────────────────────────────────────────

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS claude_token_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    project             TEXT NOT NULL,
    timestamp           TEXT NOT NULL,
    input_tokens        INTEGER DEFAULT 0,
    output_tokens       INTEGER DEFAULT 0,
    cache_create_tokens INTEGER DEFAULT 0,
    cache_read_tokens   INTEGER DEFAULT 0,
    model               TEXT,
    is_subagent         INTEGER DEFAULT 0,
    parent_session_id   TEXT,
    log_line            INTEGER DEFAULT 0,
    cost_eur            REAL DEFAULT 0,
    UNIQUE(session_id, log_line)
);
CREATE INDEX IF NOT EXISTS idx_cte_project   ON claude_token_events(project);
CREATE INDEX IF NOT EXISTS idx_cte_timestamp ON claude_token_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_cte_session   ON claude_token_events(session_id);
"""

SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS claude_token_events (
    id                  SERIAL PRIMARY KEY,
    session_id          TEXT NOT NULL,
    project             TEXT NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    input_tokens        BIGINT DEFAULT 0,
    output_tokens       BIGINT DEFAULT 0,
    cache_create_tokens BIGINT DEFAULT 0,
    cache_read_tokens   BIGINT DEFAULT 0,
    model               TEXT,
    is_subagent         BOOLEAN DEFAULT FALSE,
    parent_session_id   TEXT,
    log_line            INTEGER DEFAULT 0,
    cost_eur            NUMERIC(12,8) DEFAULT 0,
    UNIQUE(session_id, log_line)
);
CREATE INDEX IF NOT EXISTS idx_cte_project   ON claude_token_events(project);
CREATE INDEX IF NOT EXISTS idx_cte_timestamp ON claude_token_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_cte_session   ON claude_token_events(session_id);
"""

def ensure_schema(conn):
    cur = get_cursor(conn)
    schema = SCHEMA_POSTGRES if DB_TYPE == "postgres" else SCHEMA_SQLITE
    for stmt in schema.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            cur.execute(stmt)
    if DB_TYPE != "postgres":
        conn.commit()

# ── Upsert ────────────────────────────────────────────────────────────────

def upsert_events(conn, events):
    """Inserisce eventi ignorando duplicati (session_id, log_line)."""
    if not events:
        return 0
    cur = get_cursor(conn)
    sql = """
        INSERT INTO claude_token_events
            (session_id, project, timestamp, input_tokens, output_tokens,
             cache_create_tokens, cache_read_tokens, model,
             is_subagent, parent_session_id, log_line, cost_eur)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (session_id, log_line) DO NOTHING
    """ if DB_TYPE == "sqlite" else """
        INSERT INTO claude_token_events
            (session_id, project, timestamp, input_tokens, output_tokens,
             cache_create_tokens, cache_read_tokens, model,
             is_subagent, parent_session_id, log_line, cost_eur)
        VALUES (%(session_id)s, %(project)s, %(timestamp)s, %(input_tokens)s, %(output_tokens)s,
                %(cache_create_tokens)s, %(cache_read_tokens)s, %(model)s,
                %(is_subagent)s, %(parent_session_id)s, %(log_line)s, %(cost_eur)s)
        ON CONFLICT (session_id, log_line) DO NOTHING
    """
    if DB_TYPE == "sqlite":
        params = [(
            e["session_id"], e["project"], e["timestamp"],
            e["input_tokens"], e["output_tokens"],
            e["cache_create_tokens"], e["cache_read_tokens"], e["model"],
            1 if e["is_subagent"] else 0,
            e["parent_session_id"], e["log_line"], e["cost_eur"]
        ) for e in events]
        cur.executemany(sql, params)
        conn.commit()
    else:
        import psycopg2.extras
        psycopg2.extras.execute_batch(cur, sql, events, page_size=500)
    return len(events)
