# Claude Token Guard

Dashboard per monitorare il consumo di token nelle sessioni Claude Code, per progetto.

## Installazione (2 minuti)

```bash
git clone <repo-url> token-guard
cd token-guard
bash install.sh
```

Poi apri **http://localhost:4001**

## Requisiti

- Python 3.8+
- Claude Code installato (almeno una sessione)
- Nessun altro requisito (usa SQLite di default)

## Cosa mostra

- Token totali per progetto (input / output / cache)
- **Ultima sessione** — consumo dell'ultima sessione, inclusi subagents (Task tool)
- Cache Hit % — quanto contesto viene servito dalla cache vs riscritto
- API Equiv. — costo equivalente a prezzi API (utile per confronto, ≠ costo piano Max)
- Filtri: Oggi / 7 giorni / range custom
- Ordinamento per qualsiasi colonna

## Configurazione

Apri `config.py` e modifica le impostazioni:

```python
# Porta della dashboard
SERVER_PORT = 4001

# Backend DB (default: sqlite, zero setup)
# Per Postgres: DB_TYPE = "postgres" + imposta PG_*
DB_TYPE = "sqlite"
```

## Postgres (opzionale)

Se vuoi usare Postgres invece di SQLite:

```python
# config.py
DB_TYPE = "postgres"
PG_HOST = "localhost"
PG_PORT = 5432
PG_DB   = "mydb"
PG_USER = "postgres"
PG_PASS = "password"
```

Poi: `pip install psycopg2-binary` e `bash install.sh`

## File

| File | Descrizione |
|------|-------------|
| `config.py` | Tutte le impostazioni |
| `collector.py` | Legge i JSONL di Claude Code, scrive nel DB |
| `api_server.py` | Server HTTP — API JSON + dashboard HTML |
| `dashboard.html` | Frontend (polling 30s) |
| `db.py` | Compatibilità SQLite/Postgres |
| `install.sh` | Installer automatico |

## Aggiornamento dati

Il collector gira ogni 30 secondi via crontab. Puoi eseguirlo manualmente:

```bash
python3 collector.py
```

## Disinstallazione

```bash
pm2 delete token-guard       # ferma il server
crontab -e                   # rimuovi le righe "Claude Token Guard"
rm -rf ~/.claude-token-guard # rimuovi il DB SQLite
```
