#!/bin/bash
# Claude Token Guard — installer
# Uso: bash install.sh

set -e

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTOR="$INSTALL_DIR/collector.py"
SERVER="$INSTALL_DIR/api_server.py"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║      Claude Token Guard Setup        ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. Python ─────────────────────────────────────────────────────────────
echo "▸ Controllo Python 3..."
if ! command -v python3 &>/dev/null; then
    echo "  ✗ Python 3 non trovato. Installa Python 3.8+ e riprova."
    exit 1
fi
PY_VER=$(python3 --version 2>&1)
echo "  ✓ $PY_VER"

# ── 2. Verifica log Claude Code ───────────────────────────────────────────
echo "▸ Controllo log Claude Code..."
CLAUDE_DIR="${HOME}/.claude/projects"
if [ ! -d "$CLAUDE_DIR" ]; then
    echo "  ⚠ Directory $CLAUDE_DIR non trovata."
    echo "    Assicurati di aver usato Claude Code almeno una volta."
    echo "    Puoi cambiare il path in config.py → CLAUDE_PROJECTS_DIR"
else
    N=$(find "$CLAUDE_DIR" -name "*.jsonl" -not -path "*/subagents/*" 2>/dev/null | wc -l | tr -d ' ')
    echo "  ✓ Trovati $N file di sessione in $CLAUDE_DIR"
fi

# ── 3. Config ─────────────────────────────────────────────────────────────
echo "▸ Configurazione..."
DB_TYPE=$(python3 -c "import sys; sys.path.insert(0,'$INSTALL_DIR'); from config import DB_TYPE; print(DB_TYPE)" 2>/dev/null || echo "sqlite")
PORT=$(python3 -c "import sys; sys.path.insert(0,'$INSTALL_DIR'); from config import SERVER_PORT; print(SERVER_PORT)" 2>/dev/null || echo "4001")

if [ "$DB_TYPE" = "postgres" ]; then
    echo "  → Backend: Postgres"
    echo "  ▸ Installazione psycopg2..."
    pip3 install psycopg2-binary -q --break-system-packages 2>/dev/null || \
    pip3 install psycopg2-binary -q 2>/dev/null || \
    pip install psycopg2-binary -q 2>/dev/null || \
    { echo "  ⚠ Impossibile installare psycopg2. Installa manualmente: pip install psycopg2-binary"; }
    echo "  ✓ psycopg2 pronto"
else
    echo "  → Backend: SQLite (zero setup)"
    DB_PATH=$(python3 -c "import sys; sys.path.insert(0,'$INSTALL_DIR'); from config import DB_SQLITE_PATH; print(DB_SQLITE_PATH)" 2>/dev/null || echo "~/.claude-token-guard/tokens.db")
    echo "  → DB: $DB_PATH"
fi

echo "  → Porta: $PORT"

# ── 4. Prima raccolta dati ────────────────────────────────────────────────
echo "▸ Prima raccolta dati (backfill storico)..."
cd "$INSTALL_DIR"
python3 collector.py 2>&1 | tail -3
echo "  ✓ Dati storici importati"

# ── 5. Crontab (ogni 30 secondi) ─────────────────────────────────────────
echo "▸ Configurazione crontab..."
CRON1="* * * * * cd $INSTALL_DIR && python3 $COLLECTOR >> $INSTALL_DIR/collector.log 2>&1"
CRON2="* * * * * sleep 30 && cd $INSTALL_DIR && python3 $COLLECTOR >> $INSTALL_DIR/collector.log 2>&1"

( crontab -l 2>/dev/null | grep -v "claude-token-guard\|Token-Guard" ; \
  echo "# Claude Token Guard"; \
  echo "$CRON1"; \
  echo "$CRON2" ) | crontab -
echo "  ✓ Collector ogni 30 secondi"

# ── 6. Avvio server ───────────────────────────────────────────────────────
echo "▸ Avvio dashboard server..."
cd "$INSTALL_DIR"

# PM2 se disponibile, altrimenti nohup
if command -v pm2 &>/dev/null; then
    pm2 delete token-guard 2>/dev/null || true
    pm2 start api_server.py --name "token-guard" --interpreter python3
    pm2 save 2>/dev/null || true
    echo "  ✓ Server avviato con PM2 (si riavvia automaticamente)"
else
    pkill -f "api_server.py" 2>/dev/null || true
    nohup python3 "$SERVER" > "$INSTALL_DIR/server.log" 2>&1 &
    echo "  ✓ Server avviato (PID $!)"
    echo "  ℹ Per riavvio automatico installa PM2: npm install -g pm2"
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  ✓ Installazione completata!         ║"
echo "║                                      ║"
echo "║  Dashboard: http://localhost:$PORT     ║"
echo "║                                      ║"
echo "║  Aggiornamento dati: ogni 30s        ║"
echo "║  Log collector: $INSTALL_DIR/collector.log"
echo "╚══════════════════════════════════════╝"
echo ""
