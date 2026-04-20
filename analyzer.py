#!/usr/bin/env python3
"""
Claude Token Guard — Qualitative Analyzer
Zero API calls — pure structural analysis of JSONL files.
Extracts tool usage patterns, context metrics, and behavioral signals
to diagnose inefficient usage without reading any message content.
"""
import json

# ── Tool classification ──────────────────────────────────────────────────────
EXPLORATION_TOOLS = {
    "Bash", "Read", "Grep", "Glob", "WebFetch", "WebSearch",
    "ListMcpResourcesTool", "ReadMcpResourceTool", "ToolSearch",
}
IMPLEMENTATION_TOOLS = {"Edit", "Write", "NotebookEdit"}
DELEGATION_TOOLS = {"Task"}

# ── Diagnosis rules ──────────────────────────────────────────────────────────
# severity: 1=info 2=warning 3=alert 4=critical
RULES = [
    {
        "id":       "HIGH_CONTEXT_STARTUP",
        "label":    "Contesto iniziale enorme",
        "severity": 2,
        "detail":   "Primo turno: {val}k token di cache. CLAUDE.md o skill troppo pesanti — considera di ridurli.",
        "check":    lambda m: m["context_initial_tokens"] > 25_000,
        "val":      lambda m: round(m["context_initial_tokens"] / 1000, 1),
    },
    {
        "id":       "CONTEXT_BALLOONING",
        "label":    "Contesto in espansione rapida",
        "severity": 3,
        "detail":   "Crescita media {val}k token/turno. File enormi nel progetto o loop di lettura ridondanti.",
        "check":    lambda m: m["context_growth_rate"] > 7_000 and m["turn_count"] >= 3,
        "val":      lambda m: round(m["context_growth_rate"] / 1000, 1),
    },
    {
        "id":       "EXPLORATION_HEAVY",
        "label":    "Troppa esplorazione, poca produzione",
        "severity": 2,
        "detail":   "{val}% dei tool call sono Read/Grep/Bash. Progetto poco documentato o domande troppo aperte.",
        "check":    lambda m: m["exploration_ratio"] > 0.75 and m["tool_call_count"] >= 10,
        "val":      lambda m: round(m["exploration_ratio"] * 100),
    },
    {
        "id":       "SUBAGENT_HEAVY",
        "label":    "Delega eccessiva a subagent",
        "severity": 3,
        "detail":   "{val}% dei tool call sono Task/subagent. Costo moltiplicato — valuta se necessario.",
        "check":    lambda m: m["delegation_ratio"] > 0.25 and m["tool_call_count"] >= 4,
        "val":      lambda m: round(m["delegation_ratio"] * 100),
    },
    {
        "id":       "COMPLEX_QUESTIONS",
        "label":    "Domande molto complesse per turno",
        "severity": 2,
        "detail":   "Media {val} tool call/turno. Considera di spezzare le richieste in step più piccoli.",
        "check":    lambda m: m["avg_tool_calls_per_turn"] > 8,
        "val":      lambda m: round(m["avg_tool_calls_per_turn"], 1),
    },
    {
        "id":       "THINKING_OVERHEAD",
        "label":    "Extended thinking attivo",
        "severity": 1,
        "detail":   "Extended thinking in {val} turni — molto costoso su task routinari.",
        "check":    lambda m: m["thinking_turns"] > 0,
        "val":      lambda m: m["thinking_turns"],
    },
    {
        "id":       "LOW_CACHE_EFFICIENCY",
        "label":    "Cache read scarsa",
        "severity": 2,
        "detail":   "Cache read solo {val}% del contesto dopo >5 turni. Sessioni troppo brevi o context reset frequenti.",
        "check":    lambda m: m["cache_read_ratio"] < 0.30 and m["turn_count"] > 5,
        "val":      lambda m: round(m["cache_read_ratio"] * 100, 1),
    },
    {
        "id":       "LONG_QUESTIONS",
        "label":    "Messaggi utente molto lunghi",
        "severity": 1,
        "detail":   "Media {val} caratteri/messaggio. Domande molto verbose aumentano il contesto inutilmente.",
        "check":    lambda m: m["avg_user_msg_len"] > 800,
        "val":      lambda m: round(m["avg_user_msg_len"]),
    },
]


def analyze_session(filepath):
    """
    Parse a JSONL session file and return qualitative metrics dict.
    Returns None if the file is unreadable or has no meaningful content.
    """
    turns = []        # [{user_text, tools, has_thinking, cache_create, cache_read, input, output}]
    current_turn = None

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue

                t = d.get("type")

                if t == "user":
                    msg     = d.get("message", {})
                    content = msg.get("content", [])
                    texts   = []
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                texts.append(c.get("text", ""))
                    elif isinstance(content, str):
                        texts = [content]
                    if texts:
                        # Genuine user message (not a tool_result)
                        current_turn = {
                            "user_text":    " ".join(texts),
                            "tools":        [],
                            "has_thinking": False,
                            "cache_create": 0,
                            "cache_read":   0,
                            "input":        0,
                            "output":       0,
                        }
                        turns.append(current_turn)

                elif t == "assistant":
                    msg     = d.get("message", {})
                    content = msg.get("content", [])
                    usage   = msg.get("usage", {})

                    if current_turn is None:
                        # Assistant message before first user turn (system preamble)
                        current_turn = {
                            "user_text":    "",
                            "tools":        [],
                            "has_thinking": False,
                            "cache_create": 0,
                            "cache_read":   0,
                            "input":        0,
                            "output":       0,
                        }
                        turns.append(current_turn)

                    if isinstance(content, list):
                        for item in content:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") == "thinking":
                                current_turn["has_thinking"] = True
                            elif item.get("type") == "tool_use":
                                current_turn["tools"].append(item.get("name", "unknown"))

                    cc  = int(usage.get("cache_creation_input_tokens", 0) or 0)
                    cr  = int(usage.get("cache_read_input_tokens",    0) or 0)
                    inp = int(usage.get("input_tokens",               0) or 0)
                    out = int(usage.get("output_tokens",              0) or 0)

                    # Use max for context/input (same growing window), accumulate output
                    current_turn["cache_create"] = max(current_turn["cache_create"], cc)
                    current_turn["cache_read"]   = max(current_turn["cache_read"],   cr)
                    current_turn["input"]        = max(current_turn["input"],        inp)
                    current_turn["output"]      += out

    except Exception:
        return None

    if not turns:
        return None

    # ── Compute metrics ──────────────────────────────────────────────────────
    turn_count = len(turns)

    all_tools       = [tool for turn in turns for tool in turn["tools"]]
    tool_call_count = len(all_tools)

    tool_freq = {}
    for tool in all_tools:
        tool_freq[tool] = tool_freq.get(tool, 0) + 1

    exploration_calls    = sum(v for k, v in tool_freq.items() if k in EXPLORATION_TOOLS)
    implementation_calls = sum(v for k, v in tool_freq.items() if k in IMPLEMENTATION_TOOLS)
    delegation_calls     = sum(v for k, v in tool_freq.items() if k in DELEGATION_TOOLS)

    exploration_ratio       = exploration_calls / tool_call_count if tool_call_count else 0.0
    delegation_ratio        = delegation_calls  / tool_call_count if tool_call_count else 0.0
    avg_tool_calls_per_turn = tool_call_count   / turn_count      if turn_count      else 0.0

    thinking_turns = sum(1 for t in turns if t["has_thinking"])

    context_initial_tokens = turns[0]["cache_create"] if turns else 0

    cache_creates = [t["cache_create"] for t in turns]
    if len(cache_creates) > 1:
        deltas = [
            cache_creates[i] - cache_creates[i - 1]
            for i in range(1, len(cache_creates))
            if cache_creates[i] > cache_creates[i - 1]
        ]
        context_growth_rate = sum(deltas) / len(deltas) if deltas else 0.0
    else:
        context_growth_rate = 0.0

    total_input_full = sum(t["input"] + t["cache_create"] + t["cache_read"] for t in turns)
    total_cache_read = sum(t["cache_read"] for t in turns)
    cache_read_ratio = total_cache_read / total_input_full if total_input_full else 0.0

    user_msgs        = [t["user_text"] for t in turns if t["user_text"].strip()]
    avg_user_msg_len = sum(len(m) for m in user_msgs) / len(user_msgs) if user_msgs else 0.0

    total_output      = sum(t["output"] for t in turns)
    total_tokens_full = sum(t["input"] + t["output"] + t["cache_create"] + t["cache_read"] for t in turns)
    output_efficiency = total_output / total_tokens_full if total_tokens_full else 0.0

    top_tools = dict(sorted(tool_freq.items(), key=lambda x: x[1], reverse=True)[:8])

    metrics = {
        "turn_count":               turn_count,
        "tool_call_count":          tool_call_count,
        "avg_tool_calls_per_turn":  round(avg_tool_calls_per_turn,  2),
        "exploration_calls":        exploration_calls,
        "implementation_calls":     implementation_calls,
        "delegation_calls":         delegation_calls,
        "exploration_ratio":        round(exploration_ratio,   3),
        "delegation_ratio":         round(delegation_ratio,    3),
        "thinking_turns":           thinking_turns,
        "context_initial_tokens":   context_initial_tokens,
        "context_growth_rate":      round(context_growth_rate, 1),
        "cache_read_ratio":         round(cache_read_ratio,    3),
        "avg_user_msg_len":         round(avg_user_msg_len,    1),
        "output_efficiency":        round(output_efficiency,   3),
        "top_tools":                top_tools,
    }

    # ── Diagnosis ────────────────────────────────────────────────────────────
    diagnosis    = []
    max_severity = 0
    for rule in RULES:
        try:
            if rule["check"](metrics):
                val    = rule["val"](metrics) if "val" in rule else ""
                detail = rule["detail"].format(val=val)
                diagnosis.append({
                    "id":       rule["id"],
                    "label":    rule["label"],
                    "severity": rule["severity"],
                    "detail":   detail,
                })
                max_severity = max(max_severity, rule["severity"])
        except Exception:
            pass

    metrics["diagnosis"]    = diagnosis
    metrics["max_severity"] = max_severity
    return metrics
