#!/usr/bin/env python3
"""
Claude Token Guard — API Server
Serve la dashboard su http://localhost:PORT
"""
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

import db
from config import SERVER_PORT, DB_TYPE


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Non-blocking server — each request runs in its own thread.
    Required for the /api/ask-opus endpoint which can take 10-30s."""
    daemon_threads = True

DASHBOARD_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")

# ── Query helpers ─────────────────────────────────────────────────────────

def _range_clause(params, from_dt, to_dt):
    """Ritorna (clause, params_updated) per il filtro data."""
    clauses = []
    if from_dt:
        clauses.append("timestamp >= :from_dt" if DB_TYPE == "sqlite" else "timestamp >= %(from_dt)s")
        params["from_dt"] = from_dt
    if to_dt:
        clauses.append("timestamp <= :to_dt" if DB_TYPE == "sqlite" else "timestamp <= %(to_dt)s")
        params["to_dt"] = to_dt
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params

def _exec(cur, sql, params=None):
    if params is None:
        cur.execute(sql)
    elif DB_TYPE == "sqlite":
        cur.execute(sql, params)
    else:
        cur.execute(sql, params)

def _now_minus_minutes(n):
    dt = datetime.now(timezone.utc) - timedelta(minutes=n)
    return dt.isoformat()

def get_data(from_dt=None, to_dt=None):
    conn = db.get_conn()
    cur  = db.get_cursor(conn)
    p = {}
    where, p = _range_clause(p, from_dt, to_dt)

    # 1 — Totali per progetto
    _exec(cur, f"""
        SELECT
            project,
            SUM(input_tokens)          AS total_input,
            SUM(output_tokens)         AS total_output,
            SUM(cache_create_tokens)   AS total_cache_create,
            SUM(cache_read_tokens)     AS total_cache_read,
            SUM(input_tokens + output_tokens + cache_create_tokens + cache_read_tokens) AS total_tokens,
            SUM(cost_eur)              AS api_equiv_eur,
            MAX(timestamp)             AS last_activity,
            MAX(model)                 AS model
        FROM claude_token_events
        {where}
        GROUP BY project
        ORDER BY last_activity DESC
    """, p or None)
    totals = {r["project"]: dict(r) for r in db.rows_as_dicts(cur)}

    # 2 — Sessioni principali per progetto
    _exec(cur, f"""
        SELECT project, COUNT(DISTINCT session_id) AS sessions
        FROM claude_token_events
        {where}
        {"AND" if where else "WHERE"} is_subagent {"= 0" if DB_TYPE == "sqlite" else "= FALSE"}
        GROUP BY project
    """, p or None)
    for r in db.rows_as_dicts(cur):
        if r["project"] in totals:
            totals[r["project"]]["sessions"] = r["sessions"]

    # 3 — Ultima sessione per progetto (Python-side)
    _exec(cur, f"""
        SELECT project, session_id, MAX(timestamp) AS max_ts
        FROM claude_token_events
        {where}
        {"AND" if where else "WHERE"} is_subagent {"= 0" if DB_TYPE == "sqlite" else "= FALSE"}
        GROUP BY project, session_id
        ORDER BY max_ts DESC
    """, p or None)
    last_sess = {}
    for r in db.rows_as_dicts(cur):
        proj = r["project"]
        if proj not in last_sess:
            last_sess[proj] = r["session_id"]

    # 4 — Stats ultima sessione (inclusi subagents)
    now5 = _now_minus_minutes(5)
    projects = []
    for proj, data in totals.items():
        ls_id = last_sess.get(proj)
        if ls_id:
            _exec(cur, f"""
                SELECT
                    SUM(input_tokens)  AS ls_input,
                    SUM(output_tokens) AS ls_output,
                    SUM(input_tokens + output_tokens + cache_create_tokens + cache_read_tokens) AS ls_tokens,
                    SUM(cost_eur)      AS ls_cost_eur,
                    COUNT(DISTINCT CASE WHEN is_subagent {"= 1" if DB_TYPE == "sqlite" else ""} THEN session_id END) AS ls_subagents
                FROM claude_token_events
                {where}
                {"AND" if where else "WHERE"} (session_id = {'?' if DB_TYPE == 'sqlite' else '%s'}
                   OR parent_session_id = {'?' if DB_TYPE == 'sqlite' else '%s'})
            """, ({**p, "s1": ls_id, "s2": ls_id} if DB_TYPE != "sqlite" else
                  list(p.values()) + [ls_id, ls_id]) if p else
                 ([ls_id, ls_id] if DB_TYPE == "sqlite" else {"s1": ls_id, "s2": ls_id}))

            ls = db.rows_as_dicts(cur)
            ls = ls[0] if ls else {}
        else:
            ls = {}

        inp  = data.get("total_input") or 0
        cr   = data.get("total_cache_read") or 0
        cc   = data.get("total_cache_create") or 0
        denom = inp + cr + cc
        cache_hit_pct = round(100.0 * cr / denom, 1) if denom else 0

        turns = sum([
            int(data.get("total_input") or 0),
        ])

        last_act = data.get("last_activity") or ""
        is_active = bool(last_act and last_act >= now5)

        projects.append({
            "project":           proj,
            "model":             data.get("model"),
            "sessions":          data.get("sessions", 0),
            "total_input":       int(data.get("total_input") or 0),
            "total_output":      int(data.get("total_output") or 0),
            "total_cache_create":int(data.get("total_cache_create") or 0),
            "total_cache_read":  int(data.get("total_cache_read") or 0),
            "total_tokens":      int(data.get("total_tokens") or 0),
            "api_equiv_eur":     round(float(data.get("api_equiv_eur") or 0), 2),
            "last_activity":     last_act,
            "is_active":         is_active,
            "cache_hit_pct":     cache_hit_pct,
            "avg_input_per_turn":0,
            "ls_tokens":    int(ls.get("ls_tokens") or 0) or None,
            "ls_input":     int(ls.get("ls_input") or 0) or None,
            "ls_output":    int(ls.get("ls_output") or 0) or None,
            "ls_cost_eur":  round(float(ls.get("ls_cost_eur") or 0), 4) or None,
            "ls_subagents": int(ls.get("ls_subagents") or 0),
        })

    # 5 — Andamento orario
    trunc = "strftime('%Y-%m-%dT%H:00:00', timestamp)" if DB_TYPE == "sqlite" \
        else "DATE_TRUNC('hour', timestamp)"
    _exec(cur, f"""
        SELECT project, {trunc} AS hour,
            SUM(input_tokens + output_tokens + cache_create_tokens + cache_read_tokens) AS tokens,
            SUM(cost_eur) AS cost_eur
        FROM claude_token_events
        {where}
        GROUP BY project, {trunc}
        ORDER BY hour DESC
        LIMIT 500
    """, p or None)
    hourly = [{"project": r["project"], "hour": str(r["hour"]),
               "tokens": int(r["tokens"] or 0),
               "cost_eur": round(float(r["cost_eur"] or 0), 4)}
              for r in db.rows_as_dicts(cur)]

    # 6 — Summary
    _exec(cur, f"""
        SELECT
            COUNT(DISTINCT project)   AS total_projects,
            SUM(input_tokens + output_tokens + cache_create_tokens + cache_read_tokens) AS grand_total_tokens,
            SUM(cost_eur)             AS grand_api_equiv_eur,
            SUM(cache_read_tokens)    AS cr,
            SUM(input_tokens + cache_read_tokens + cache_create_tokens) AS denom,
            SUM(output_tokens)        AS total_out
        FROM claude_token_events
        {where}
    """, p or None)
    sr = db.rows_as_dicts(cur)[0]
    cr_s  = float(sr.get("cr") or 0)
    den_s = float(sr.get("denom") or 1)
    out_s = float(sr.get("total_out") or 0)
    summary = {
        "total_projects":       int(sr.get("total_projects") or 0),
        "total_sessions":       sum(p2.get("sessions", 0) for p2 in projects),
        "grand_total_tokens":   int(sr.get("grand_total_tokens") or 0),
        "grand_api_equiv_eur":  round(float(sr.get("grand_api_equiv_eur") or 0), 2),
        "global_cache_hit_pct": round(100.0 * cr_s / den_s, 1) if den_s else 0,
        "output_ratio_pct":     round(100.0 * out_s / den_s, 1) if den_s else 0,
    }

    conn.close()
    return {"projects": projects, "hourly": hourly, "summary": summary,
            "generated_at": datetime.now(timezone.utc).isoformat()}


def get_analysis(project):
    """Qualitative analysis for a single project — all sessions + aggregate."""
    conn = db.get_conn()
    sessions = db.get_project_analysis(conn, project)
    conn.close()

    if not sessions:
        return {"project": project, "sessions": [], "aggregate": {"session_count": 0}}

    def _avg(key):
        vals = [s[key] for s in sessions if s.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else 0

    # Aggregate flag counts across sessions
    flag_counts = {}
    for s in sessions:
        for d in s.get("diagnosis", []):
            fid = d["id"]
            if fid not in flag_counts:
                flag_counts[fid] = {
                    "id": fid, "label": d["label"],
                    "severity": d["severity"], "count": 0,
                }
            flag_counts[fid]["count"] += 1

    aggregate = {
        "session_count":              len(sessions),
        "avg_turn_count":             _avg("turn_count"),
        "avg_tool_calls_per_turn":    _avg("avg_tool_calls_per_turn"),
        "avg_context_initial_tokens": _avg("context_initial_tokens"),
        "avg_context_growth_rate":    _avg("context_growth_rate"),
        "avg_cache_read_ratio":       _avg("cache_read_ratio"),
        "avg_exploration_ratio":      _avg("exploration_ratio"),
        "avg_delegation_ratio":       _avg("delegation_ratio"),
        "avg_output_efficiency":      _avg("output_efficiency"),
        "max_severity":               max((s.get("max_severity", 0) for s in sessions), default=0),
        "flag_counts":                sorted(flag_counts.values(),
                                            key=lambda x: (-x["severity"], -x["count"])),
    }

    return {"project": project, "sessions": sessions, "aggregate": aggregate}


def get_alerts():
    """All sessions with at least one diagnosis flag, for dashboard polling."""
    conn = db.get_conn()
    alerts = db.get_all_alerts(conn, min_severity=1)
    conn.close()
    return {"alerts": alerts}

# ── HTTP Handler ──────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        from_dt = qs.get("from", [None])[0]
        to_dt   = qs.get("to",   [None])[0]

        if parsed.path == "/api/data":
            try:
                body = json.dumps(get_data(from_dt, to_dt)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif parsed.path == "/api/analysis":
            project = qs.get("project", [None])[0]
            try:
                if not project:
                    raise ValueError("project param required")
                body = json.dumps(get_analysis(project)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(400 if "required" in str(e) else 500)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif parsed.path == "/api/alerts":
            try:
                body = json.dumps(get_alerts()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif parsed.path == "/api/ask-opus":
            project = qs.get("project", [None])[0]
            try:
                if not project:
                    raise ValueError("project param required")
                import claude_advisor
                analysis = get_analysis(project)
                if not analysis["sessions"]:
                    raise ValueError(f"Nessuna analisi disponibile per '{project}'. Attendi il prossimo ciclo del collector.")
                result = claude_advisor.ask_opus(
                    project,
                    analysis["aggregate"],
                    analysis["sessions"],
                )
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                code = 400 if ("required" in str(e) or "Nessuna" in str(e)) else 500
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e), "text": None}).encode())

        elif parsed.path in ("/", "/index.html"):
            try:
                body = open(DASHBOARD_HTML, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_cors()
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    conn = db.get_conn()
    db.ensure_schema(conn)
    conn.close()
    print(f"[{datetime.now():%H:%M:%S}] Token Guard → http://localhost:{SERVER_PORT}")
    ThreadingHTTPServer(("0.0.0.0", SERVER_PORT), Handler).serve_forever()
