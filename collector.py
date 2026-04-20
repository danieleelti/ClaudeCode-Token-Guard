#!/usr/bin/env python3
"""
Claude Token Guard — Collector
Legge i JSONL di Claude Code e salva i token usage nel DB.
Eseguito ogni 30s via crontab.
"""
import json
import os
import glob
from datetime import datetime, timezone

import db
import analyzer
from config import CLAUDE_PROJECTS_DIR

# Prezzi Claude (USD/token) × 0.92 EUR/USD
EUR_RATE = 0.92
PRICE = {
    "claude-opus-4":    {"in": 15e-6,  "out": 75e-6,  "cc": 18.75e-6, "cr": 1.50e-6},
    "claude-sonnet-4":  {"in": 3e-6,   "out": 15e-6,  "cc": 3.75e-6,  "cr": 0.30e-6},
    "claude-sonnet-3":  {"in": 3e-6,   "out": 15e-6,  "cc": 3.75e-6,  "cr": 0.30e-6},
    "claude-haiku-4":   {"in": 0.8e-6, "out": 4e-6,   "cc": 1.0e-6,   "cr": 0.08e-6},
    "default":          {"in": 3e-6,   "out": 15e-6,  "cc": 3.75e-6,  "cr": 0.30e-6},
}

def get_price(model):
    m = (model or "").lower()
    for key, p in PRICE.items():
        if key in m:
            return p
    return PRICE["default"]

def calc_cost(model, inp, out, cc, cr):
    p = get_price(model)
    return round((inp*p["in"] + out*p["out"] + cc*p["cc"] + cr*p["cr"]) * EUR_RATE, 8)

def slug_to_project(slug):
    for prefix in ["-root-claudecodeui-srv-", "-root-claudecodeui-svr-",
                   "-root-claudecodeui-", "-srv-", "-root-"]:
        if slug.startswith(prefix):
            return slug[len(prefix):]
    return slug.lstrip("-")

def parse_jsonl(filepath, session_id, project, is_subagent=False, parent_session_id=None):
    events = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if d.get("type") != "assistant":
                        continue
                    msg = d.get("message", {})
                    if not isinstance(msg, dict):
                        continue
                    usage = msg.get("usage")
                    if not usage:
                        continue

                    ts_str = d.get("timestamp")
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.now(timezone.utc)
                    except Exception:
                        ts = datetime.now(timezone.utc)

                    model  = msg.get("model") or d.get("model") or "unknown"
                    inp    = int(usage.get("input_tokens", 0))
                    out    = int(usage.get("output_tokens", 0))
                    cc     = int(usage.get("cache_creation_input_tokens", 0))
                    cr     = int(usage.get("cache_read_input_tokens", 0))

                    events.append({
                        "session_id":        session_id,
                        "project":           project,
                        "timestamp":         ts.isoformat(),
                        "input_tokens":      inp,
                        "output_tokens":     out,
                        "cache_create_tokens": cc,
                        "cache_read_tokens": cr,
                        "model":             model,
                        "is_subagent":       is_subagent,
                        "parent_session_id": parent_session_id,
                        "log_line":          line_num,
                        "cost_eur":          calc_cost(model, inp, out, cc, cr),
                    })
                except Exception:
                    continue
    except Exception as e:
        print(f"  [WARN] {filepath}: {e}")
    return events

def process_project(project_dir, conn):
    slug    = os.path.basename(project_dir)
    project = slug_to_project(slug)
    total   = 0

    for jsonl in glob.glob(os.path.join(project_dir, "*.jsonl")):
        session_id = os.path.splitext(os.path.basename(jsonl))[0]
        events = parse_jsonl(jsonl, session_id, project)
        n = db.upsert_events(conn, events)
        if n:
            print(f"  {project}/{session_id[:8]}… +{n}")
        total += n

        # Qualitative analysis: run if new events or no analysis yet
        if n > 0 or not db.analysis_exists(conn, session_id):
            metrics = analyzer.analyze_session(jsonl)
            if metrics:
                db.upsert_analysis(conn, session_id, project, metrics)

        # Subagent di questa sessione
        for sub in glob.glob(os.path.join(project_dir, session_id, "subagents", "*.jsonl")):
            sub_id = os.path.splitext(os.path.basename(sub))[0]
            sub_events = parse_jsonl(sub, sub_id, project, is_subagent=True, parent_session_id=session_id)
            n2 = db.upsert_events(conn, sub_events)
            if n2:
                print(f"    subagent {sub_id[:12]}… +{n2}")
            total += n2

    return total

def main():
    print(f"[{datetime.now():%H:%M:%S}] Collector START")
    conn = db.get_conn()
    db.ensure_schema(conn)

    dirs = sorted(d for d in glob.glob(os.path.join(CLAUDE_PROJECTS_DIR, "*")) if os.path.isdir(d))
    total = sum(process_project(d, conn) for d in dirs)

    conn.close()
    print(f"[{datetime.now():%H:%M:%S}] DONE +{total} righe")

if __name__ == "__main__":
    main()
