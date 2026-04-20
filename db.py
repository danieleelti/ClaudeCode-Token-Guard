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
CREATE TABLE IF NOT EXISTS session_analysis (
    session_id               TEXT PRIMARY KEY,
    project                  TEXT NOT NULL,
    analyzed_at              TEXT NOT NULL,
    turn_count               INTEGER DEFAULT 0,
    tool_call_count          INTEGER DEFAULT 0,
    avg_tool_calls_per_turn  REAL    DEFAULT 0,
    exploration_calls        INTEGER DEFAULT 0,
    implementation_calls     INTEGER DEFAULT 0,
    delegation_calls         INTEGER DEFAULT 0,
    exploration_ratio        REAL    DEFAULT 0,
    delegation_ratio         REAL    DEFAULT 0,
    thinking_turns           INTEGER DEFAULT 0,
    context_initial_tokens   INTEGER DEFAULT 0,
    context_growth_rate      REAL    DEFAULT 0,
    cache_read_ratio         REAL    DEFAULT 0,
    avg_user_msg_len         REAL    DEFAULT 0,
    output_efficiency        REAL    DEFAULT 0,
    top_tools                TEXT    DEFAULT '{}',
    diagnosis                TEXT    DEFAULT '[]',
    max_severity             INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sa_project  ON session_analysis(project);
CREATE INDEX IF NOT EXISTS idx_sa_severity ON session_analysis(max_severity);
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
CREATE TABLE IF NOT EXISTS session_analysis (
    session_id               TEXT PRIMARY KEY,
    project                  TEXT NOT NULL,
    analyzed_at              TIMESTAMPTZ NOT NULL,
    turn_count               INTEGER DEFAULT 0,
    tool_call_count          INTEGER DEFAULT 0,
    avg_tool_calls_per_turn  REAL    DEFAULT 0,
    exploration_calls        INTEGER DEFAULT 0,
    implementation_calls     INTEGER DEFAULT 0,
    delegation_calls         INTEGER DEFAULT 0,
    exploration_ratio        REAL    DEFAULT 0,
    delegation_ratio         REAL    DEFAULT 0,
    thinking_turns           INTEGER DEFAULT 0,
    context_initial_tokens   INTEGER DEFAULT 0,
    context_growth_rate      REAL    DEFAULT 0,
    cache_read_ratio         REAL    DEFAULT 0,
    avg_user_msg_len         REAL    DEFAULT 0,
    output_efficiency        REAL    DEFAULT 0,
    top_tools                TEXT    DEFAULT '{}',
    diagnosis                TEXT    DEFAULT '[]',
    max_severity             INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sa_project  ON session_analysis(project);
CREATE INDEX IF NOT EXISTS idx_sa_severity ON session_analysis(max_severity);
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

# ── Analysis ──────────────────────────────────────────────────────────────

def analysis_exists(conn, session_id):
    """Return True if a session_analysis row already exists for this session."""
    cur = get_cursor(conn)
    if DB_TYPE == "sqlite":
        cur.execute("SELECT 1 FROM session_analysis WHERE session_id = ?", [session_id])
    else:
        cur.execute("SELECT 1 FROM session_analysis WHERE session_id = %s", [session_id])
    return bool(cur.fetchone())


def upsert_analysis(conn, session_id, project, metrics):
    """Insert or replace a session_analysis row."""
    import json
    from datetime import datetime, timezone
    cur = get_cursor(conn)
    now = datetime.now(timezone.utc).isoformat()
    top_tools_json = json.dumps(metrics.get("top_tools", {}))
    diagnosis_json = json.dumps(metrics.get("diagnosis", []))
    if DB_TYPE == "sqlite":
        cur.execute("""
            INSERT OR REPLACE INTO session_analysis
                (session_id, project, analyzed_at,
                 turn_count, tool_call_count, avg_tool_calls_per_turn,
                 exploration_calls, implementation_calls, delegation_calls,
                 exploration_ratio, delegation_ratio,
                 thinking_turns, context_initial_tokens, context_growth_rate,
                 cache_read_ratio, avg_user_msg_len, output_efficiency,
                 top_tools, diagnosis, max_severity)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [
            session_id, project, now,
            metrics.get("turn_count", 0),
            metrics.get("tool_call_count", 0),
            metrics.get("avg_tool_calls_per_turn", 0),
            metrics.get("exploration_calls", 0),
            metrics.get("implementation_calls", 0),
            metrics.get("delegation_calls", 0),
            metrics.get("exploration_ratio", 0),
            metrics.get("delegation_ratio", 0),
            metrics.get("thinking_turns", 0),
            metrics.get("context_initial_tokens", 0),
            metrics.get("context_growth_rate", 0),
            metrics.get("cache_read_ratio", 0),
            metrics.get("avg_user_msg_len", 0),
            metrics.get("output_efficiency", 0),
            top_tools_json, diagnosis_json,
            metrics.get("max_severity", 0),
        ])
        conn.commit()
    else:
        cur.execute("""
            INSERT INTO session_analysis
                (session_id, project, analyzed_at,
                 turn_count, tool_call_count, avg_tool_calls_per_turn,
                 exploration_calls, implementation_calls, delegation_calls,
                 exploration_ratio, delegation_ratio,
                 thinking_turns, context_initial_tokens, context_growth_rate,
                 cache_read_ratio, avg_user_msg_len, output_efficiency,
                 top_tools, diagnosis, max_severity)
            VALUES (%(session_id)s,%(project)s,%(analyzed_at)s,
                    %(turn_count)s,%(tool_call_count)s,%(avg_tool_calls_per_turn)s,
                    %(exploration_calls)s,%(implementation_calls)s,%(delegation_calls)s,
                    %(exploration_ratio)s,%(delegation_ratio)s,
                    %(thinking_turns)s,%(context_initial_tokens)s,%(context_growth_rate)s,
                    %(cache_read_ratio)s,%(avg_user_msg_len)s,%(output_efficiency)s,
                    %(top_tools)s,%(diagnosis)s,%(max_severity)s)
            ON CONFLICT (session_id) DO UPDATE SET
                project=EXCLUDED.project, analyzed_at=EXCLUDED.analyzed_at,
                turn_count=EXCLUDED.turn_count, tool_call_count=EXCLUDED.tool_call_count,
                avg_tool_calls_per_turn=EXCLUDED.avg_tool_calls_per_turn,
                exploration_calls=EXCLUDED.exploration_calls,
                implementation_calls=EXCLUDED.implementation_calls,
                delegation_calls=EXCLUDED.delegation_calls,
                exploration_ratio=EXCLUDED.exploration_ratio,
                delegation_ratio=EXCLUDED.delegation_ratio,
                thinking_turns=EXCLUDED.thinking_turns,
                context_initial_tokens=EXCLUDED.context_initial_tokens,
                context_growth_rate=EXCLUDED.context_growth_rate,
                cache_read_ratio=EXCLUDED.cache_read_ratio,
                avg_user_msg_len=EXCLUDED.avg_user_msg_len,
                output_efficiency=EXCLUDED.output_efficiency,
                top_tools=EXCLUDED.top_tools,
                diagnosis=EXCLUDED.diagnosis,
                max_severity=EXCLUDED.max_severity
        """, {
            "session_id": session_id, "project": project, "analyzed_at": now,
            "turn_count": metrics.get("turn_count", 0),
            "tool_call_count": metrics.get("tool_call_count", 0),
            "avg_tool_calls_per_turn": metrics.get("avg_tool_calls_per_turn", 0),
            "exploration_calls": metrics.get("exploration_calls", 0),
            "implementation_calls": metrics.get("implementation_calls", 0),
            "delegation_calls": metrics.get("delegation_calls", 0),
            "exploration_ratio": metrics.get("exploration_ratio", 0),
            "delegation_ratio": metrics.get("delegation_ratio", 0),
            "thinking_turns": metrics.get("thinking_turns", 0),
            "context_initial_tokens": metrics.get("context_initial_tokens", 0),
            "context_growth_rate": metrics.get("context_growth_rate", 0),
            "cache_read_ratio": metrics.get("cache_read_ratio", 0),
            "avg_user_msg_len": metrics.get("avg_user_msg_len", 0),
            "output_efficiency": metrics.get("output_efficiency", 0),
            "top_tools": top_tools_json, "diagnosis": diagnosis_json,
            "max_severity": metrics.get("max_severity", 0),
        })


def get_project_analysis(conn, project):
    """Return all session analyses for a project, newest first."""
    import json as _json
    cur = get_cursor(conn)
    if DB_TYPE == "sqlite":
        cur.execute("""
            SELECT * FROM session_analysis WHERE project = ?
            ORDER BY max_severity DESC, analyzed_at DESC
        """, [project])
    else:
        cur.execute("""
            SELECT * FROM session_analysis WHERE project = %s
            ORDER BY max_severity DESC, analyzed_at DESC
        """, [project])
    rows = rows_as_dicts(cur)
    for r in rows:
        r["diagnosis"] = _json.loads(r.get("diagnosis") or "[]")
        r["top_tools"] = _json.loads(r.get("top_tools") or "{}")
    return rows


def get_all_alerts(conn, min_severity=1):
    """Return sessions with max_severity >= min_severity across all projects."""
    import json as _json
    cur = get_cursor(conn)
    if DB_TYPE == "sqlite":
        cur.execute("""
            SELECT session_id, project, analyzed_at, max_severity, diagnosis
            FROM session_analysis
            WHERE max_severity >= ?
            ORDER BY max_severity DESC, analyzed_at DESC
            LIMIT 200
        """, [min_severity])
    else:
        cur.execute("""
            SELECT session_id, project, analyzed_at, max_severity, diagnosis
            FROM session_analysis
            WHERE max_severity >= %s
            ORDER BY max_severity DESC, analyzed_at DESC
            LIMIT 200
        """, [min_severity])
    rows = rows_as_dicts(cur)
    for r in rows:
        r["diagnosis"] = _json.loads(r.get("diagnosis") or "[]")
    return rows


# ── Events ────────────────────────────────────────────────────────────────

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
