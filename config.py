"""
Claude Token Guard — configurazione
Modifica questo file prima di installare.
"""
import os

# ── Database ──────────────────────────────────────────────────────────────
# "sqlite"   → zero setup, file locale (~/.claude-token-guard/tokens.db)
# "postgres" → richiede Postgres; imposta le variabili PG_* sotto
DB_TYPE = os.getenv("TOKEN_DB_TYPE", "sqlite")

# SQLite: path del file DB (auto-creato al primo avvio)
DB_SQLITE_PATH = os.path.expanduser(
    os.getenv("TOKEN_DB_PATH", "~/.claude-token-guard/tokens.db")
)

# Postgres (solo se DB_TYPE=postgres)
PG_HOST = os.getenv("TOKEN_PG_HOST", "localhost")
PG_PORT = int(os.getenv("TOKEN_PG_PORT", "5432"))
PG_DB   = os.getenv("TOKEN_PG_DB",   "postgres")
PG_USER = os.getenv("TOKEN_PG_USER", "postgres")
PG_PASS = os.getenv("TOKEN_PG_PASS", "")

# ── Claude Code ───────────────────────────────────────────────────────────
# Path dei log di Claude Code (uguale su tutti i sistemi)
CLAUDE_PROJECTS_DIR = os.path.expanduser(
    os.getenv("TOKEN_CLAUDE_DIR", "~/.claude/projects")
)

# ── Dashboard ─────────────────────────────────────────────────────────────
SERVER_PORT = int(os.getenv("TOKEN_PORT", "4002"))
