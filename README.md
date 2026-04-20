# Claude Token Guard

Real-time token monitoring and qualitative analysis dashboard for Claude Code sessions.

Tracks token consumption per project, detects inefficient working patterns, and — optionally — calls Claude to suggest better methodology.

---

## Install (2 minutes)

```bash
git clone https://github.com/danieleelti/ClaudeCode-Token-Guard.git token-guard
cd token-guard
bash install.sh
```

Then open the dashboard at `http://<your-server-ip>:<PORT>` (default port: **4001**).

> Running locally? Use `http://localhost:4001`
> Running on a remote server? Use your server's IP or domain, e.g. `http://46.x.x.x:4001`

---

## Requirements

- Python 3.8+
- Claude Code installed with at least one session
- No other dependencies (uses SQLite by default)

---

## What it shows

### Monitor tab
- **Token totals per project** — input / output / cache read / cache write
- **Last session** — consumption of the latest session, including subagents (Task tool)
- **Cache Hit %** — how much context is served from cache vs rewritten
- **API Equiv.** — equivalent cost at API prices (useful for comparison, ≠ Max plan cost)
- **Sound alerts** — configurable threshold (L1→L4); fires when a problem is detected while you work
- Filters: Today / 7 days / custom range
- Sort by any column

### Analysis tab
Per-project qualitative analysis of working patterns — **zero extra tokens consumed**:

| Flag | What it detects |
|------|-----------------|
| `HIGH_CONTEXT_STARTUP` | Session starts with a very large context (> 50k tokens) |
| `CONTEXT_BALLOONING` | Context grows rapidly turn-over-turn (inefficient memory management) |
| `EXPLORATION_HEAVY` | Too many read/search tools vs actual implementation |
| `SUBAGENT_HEAVY` | Excessive delegation via Task tool |
| `COMPLEX_QUESTIONS` | User messages are very long (overly complex prompts) |
| `THINKING_OVERHEAD` | Extended thinking active on most turns |
| `LOW_CACHE_EFFICIENCY` | Cache hit ratio below 40% |
| `LONG_QUESTIONS` | Average user message > 500 chars |

Each flag comes with **static suggestions** — quick wins to fix the pattern.

### Claude Advisor (optional, uses tokens)
The **"Ask Claude Advisor"** button sends aggregate session metrics to Claude for a deep analysis:
- Root cause of detected inefficiencies
- Methodology improvements
- Recommended Claude Code skills and tools
- Quick wins

Requires `ANTHROPIC_API_KEY` env var (see Configuration).

---

## Configuration

All settings are controlled via environment variables. You can also edit `config.py` directly.

```bash
# Port the dashboard listens on (default: 4001)
TOKEN_PORT=4001

# Database backend: sqlite (default, zero setup) or postgres
TOKEN_DB_TYPE=sqlite

# SQLite file path (auto-created)
TOKEN_DB_PATH=~/.claude-token-guard/tokens.db

# Claude logs directory (same on all systems)
TOKEN_CLAUDE_DIR=~/.claude/projects

# For Claude Advisor feature (optional)
ANTHROPIC_API_KEY=sk-ant-...
```

### Postgres (optional)

```bash
TOKEN_DB_TYPE=postgres
TOKEN_PG_HOST=localhost
TOKEN_PG_PORT=5432
TOKEN_PG_DB=mydb
TOKEN_PG_USER=postgres
TOKEN_PG_PASS=yourpassword
```

Then: `pip install psycopg2-binary` and re-run `bash install.sh`

---

## Files

| File | Description |
|------|-------------|
| `config.py` | All settings (reads from env vars) |
| `collector.py` | Reads Claude Code JSONL logs, writes to DB |
| `analyzer.py` | Zero-cost structural analysis of sessions (8 diagnosis rules) |
| `claude_advisor.py` | Optional Claude API call for deep methodology analysis |
| `api_server.py` | HTTP server — JSON APIs + serves dashboard HTML |
| `dashboard.html` | Frontend (30s polling, Web Audio API alerts) |
| `db.py` | SQLite/Postgres compatibility layer |
| `install.sh` | Automatic installer (crontab + PM2) |

---

## How data is collected

A collector runs every 30 seconds via crontab. It reads Claude Code's JSONL session files from `~/.claude/projects/`, extracts token usage and structural metrics, and writes to the local DB. No data leaves your machine except when you explicitly click "Ask Claude Advisor".

Run manually:
```bash
python3 collector.py
```

---

## Uninstall

```bash
pm2 delete token-guard          # stop the server
crontab -e                      # remove the "Claude Token Guard" lines
rm -rf ~/.claude-token-guard    # remove the SQLite DB
```

---

## Contributing

Contributions are welcome! Here are the best places to start:

- **New diagnosis rules** — add a rule to `analyzer.py` following the existing pattern (`RULES` list, check lambda, detail template). Each rule needs a severity (1–4) and a static suggestion in `dashboard.html` (`STATIC_SUGGESTIONS` object).
- **New visualizations** — the dashboard is a single self-contained `dashboard.html` file. No build step needed.
- **Postgres improvements** — the SQLite path is battle-tested; the Postgres path could use more real-world testing.
- **Bug reports** — open a GitHub Issue with your Python version, OS, and the error output.

```
analyzer.py     ← add new diagnosis rules here
dashboard.html  ← add suggestions for new rules here (STATIC_SUGGESTIONS object)
```

PRs are reviewed within a few days. Keep changes focused — one feature or fix per PR.

---

## Privacy

- All data stays local (SQLite file on your machine)
- No telemetry, no external calls
- Claude Advisor is opt-in and explicit (you click the button, you see the token cost)
- `ANTHROPIC_API_KEY` is never written to disk — pass it as an environment variable
