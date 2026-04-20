#!/usr/bin/env python3
"""
Claude Token Guard — Opus Advisor
Calls Claude Opus API for deep, personalized methodology analysis.
Intentionally uses tokens — high-value analysis that pays for itself.
"""
import os

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = "claude-opus-4-5"

# ── Context about available Claude Code capabilities ──────────────────────────
SKILLS_CONTEXT = """
## Tool built-in Claude Code
- **Read / Edit / Write** — file I/O preciso (preferire a Bash per file)
- **Bash** — comandi shell; costoso se usato per leggere file
- **Grep / Glob** — ricerca contenuto e pattern (usare PRIMA di Read)
- **Task** — delega a subagent specializzati (Explore, Plan, gsd-executor…)
- **WebFetch / WebSearch** — contenuti web
- **TodoWrite** — gestione task list nel flusso

## Skill ufficiali disponibili (uso: /nome)
- **/gsd:fast** — task triviali inline, zero planning, zero subagent
- **/gsd:quick** — task semplici con garanzie GSD, skip opzionali
- **/gsd:discuss-phase** — raccolta contesto adattiva prima di pianificare grandi task
- **/gsd:plan-phase** — pianificazione strutturata con verifica goal-backward
- **/gsd:map-codebase** — analisi codebase con agenti paralleli → .planning/codebase/
- **/gsd:debug** — debugging sistematico con stato persistente tra context reset
- **/gsd:parallel** — esecuzione con subagent paralleli su worktree isolati
- **/caveman** — comunicazione ultra-compressa, riduce token input ~75%
- **/graphify** — qualsiasi input → knowledge graph → HTML+JSON navigabile
- **/full-output-enforcement** — override troncamento LLM per output completo

## Pattern di ottimizzazione Claude Code
- CLAUDE.md sotto 200 righe (le righe successive vengono troncate silenziosamente)
- Documentazione di progetto frammentata in file specifici linkati da CLAUDE.md
- Grep prima di Read (trova la sezione specifica, non leggere tutto)
- Sessioni lunghe > sessioni brevi (cache read ratio cresce con la sessione)
- /caveman per task semplici come fix veloci, rename, aggiunta campi
- /gsd:map-codebase una volta per progetto → poi navigare la mappa
"""


def _build_prompt(project: str, aggregate: dict, sessions: list) -> str:
    n = aggregate.get("session_count", 0)
    flags = aggregate.get("flag_counts", [])
    sev_labels = {1: "INFO", 2: "WARNING", 3: "ALERT", 4: "CRITICO"}

    # Format diagnosis flags with detail from first matching session
    flag_lines = []
    for f in flags:
        sev = sev_labels.get(f["severity"], "?")
        flag_lines.append(
            f"**[{sev} L{f['severity']}] {f['label']}** — in {f['count']}/{n} sessioni"
        )
        for s in sessions[:5]:
            for d in s.get("diagnosis", []):
                if d["id"] == f["id"]:
                    flag_lines.append(f"  → *{d['detail']}*")
                    break
            else:
                continue
            break

    flags_block = "\n".join(flag_lines) if flag_lines else "*Nessun problema diagnosticato*"

    # Aggregate top tools across sessions
    tools_freq: dict = {}
    for s in sessions:
        for tool, cnt in (s.get("top_tools") or {}).items():
            tools_freq[tool] = tools_freq.get(tool, 0) + cnt
    top_tools_str = ", ".join(
        f"{t}×{c}" for t, c in sorted(tools_freq.items(), key=lambda x: -x[1])[:8]
    ) or "N/A"

    agg = aggregate
    return f"""Sei un esperto di Claude Code, workflow LLM e ottimizzazione token.

Analizza il profilo di utilizzo del progetto **"{project}"** ({n} sessioni) e produci consigli immediatamente applicabili.

---

## Metriche di utilizzo (medie su {n} sessioni)

| Metrica | Valore | Soglia ottimale |
|---------|--------|-----------------|
| Tool call / turno | {agg.get('avg_tool_calls_per_turn', 0):.1f} | < 8 |
| Contesto iniziale (cache creation, turno 0) | {agg.get('avg_context_initial_tokens', 0)/1000:.0f}k token | < 25k |
| Crescita contesto / turno | {agg.get('avg_context_growth_rate', 0)/1000:.1f}k token | < 7k |
| Cache read ratio | {agg.get('avg_cache_read_ratio', 0)*100:.0f}% | > 50% |
| Exploration ratio (Read/Grep/Bash) | {agg.get('avg_exploration_ratio', 0)*100:.0f}% | — |
| Delegation ratio (Task/subagent) | {agg.get('avg_delegation_ratio', 0)*100:.0f}% | — |
| Output efficiency | {agg.get('avg_output_efficiency', 0)*100:.0f}% | > 10% |
| Severità massima | L{agg.get('max_severity', 0)} | — |

**Tool più usati:** {top_tools_str}

## Problemi diagnosticati automaticamente

{flags_block}

---

{SKILLS_CONTEXT}

---

Produce un'analisi strutturata con esattamente questi header markdown:

## 🔍 Root Cause
(2-3 frasi: il problema sottostante REALE — non i sintomi ma il PERCHÉ. Collega le metriche tra loro.)

## 🛠 Metodologia Consigliata
(3-5 bullet concreti e immediatamente applicabili per questo progetto specifico. Per ogni punto: cosa cambiare, come, impatto atteso sui token.)

## 🎯 Skill e Tool Raccomandati
(lista bullet con /skill o tool. Per ogni uno: scenario specifico d'uso in questo progetto + beneficio quantificabile se possibile.)

## ⚡ Quick Win
(1-2 azioni da fare entro la prossima sessione. Massimo impatto, minimo sforzo.)

---

Rispondi in italiano. Diretto e pratico. Ogni consiglio deve essere specifico per "{project}" — niente genericità."""


def ask_opus(project: str, aggregate: dict, sessions: list) -> dict:
    """
    Call Claude Opus for deep methodology analysis.
    Returns: {text, model, input_tokens, output_tokens, error}
    """
    if not ANTHROPIC_API_KEY:
        return {
            "text": None, "model": None,
            "input_tokens": 0, "output_tokens": 0,
            "error": (
                "ANTHROPIC_API_KEY non configurata sul server. "
                "Imposta la variabile d'ambiente e riavvia Token Guard con PM2."
            ),
        }

    try:
        import anthropic  # available on system via claude-code dep
    except ImportError:
        return {
            "text": None, "model": None,
            "input_tokens": 0, "output_tokens": 0,
            "error": "Libreria 'anthropic' non trovata. Installa: pip install anthropic",
        }

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = _build_prompt(project, aggregate, sessions)

        msg = client.messages.create(
            model=MODEL,
            max_tokens=1800,
            messages=[{"role": "user", "content": prompt}],
        )

        return {
            "text": msg.content[0].text if msg.content else "",
            "model": msg.model,
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
            "error": None,
        }

    except Exception as e:
        return {
            "text": None, "model": None,
            "input_tokens": 0, "output_tokens": 0,
            "error": f"Errore API Anthropic: {e}",
        }
