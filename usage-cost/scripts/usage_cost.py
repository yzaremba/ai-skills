#!/usr/bin/env python3
"""Aggregate Claude Code session usage + list-price cost over a window.

Reads assistant-message ``message.usage`` blocks from JSONL session logs
under ``~/.claude/projects/`` and produces totals, per-day, per-project,
and top-N session tables.

CLI:
    python3 usage_cost.py [--days N] [--top N] [--no-per-day] [--no-top]

Cost is computed from public Anthropic API list prices (Opus / Sonnet /
Haiku families). On Claude Pro / Max plans actual billing is the flat
subscription, so these numbers are a *relative-burn* reference, not an
invoice preview.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# USD per 1M tokens. Keep families flat (not per-snapshot) — date-suffixed
# model ids (...-20251001) collapse to the family.
PRICING = {
    "claude-opus-4-7":   dict(inp=15.00, out=75.00, cache_read=1.50, cache_write_5m=18.75, cache_write_1h=30.00),
    "claude-opus-4-6":   dict(inp=15.00, out=75.00, cache_read=1.50, cache_write_5m=18.75, cache_write_1h=30.00),
    "claude-opus-4-5":   dict(inp=15.00, out=75.00, cache_read=1.50, cache_write_5m=18.75, cache_write_1h=30.00),
    "claude-opus-4":     dict(inp=15.00, out=75.00, cache_read=1.50, cache_write_5m=18.75, cache_write_1h=30.00),
    "claude-sonnet-4-6": dict(inp=3.00,  out=15.00, cache_read=0.30, cache_write_5m=3.75,  cache_write_1h=6.00),
    "claude-sonnet-4-5": dict(inp=3.00,  out=15.00, cache_read=0.30, cache_write_5m=3.75,  cache_write_1h=6.00),
    "claude-sonnet-4":   dict(inp=3.00,  out=15.00, cache_read=0.30, cache_write_5m=3.75,  cache_write_1h=6.00),
    "claude-haiku-4-5":  dict(inp=0.80,  out=4.00,  cache_read=0.08, cache_write_5m=1.00,  cache_write_1h=1.60),
    "claude-haiku-4":    dict(inp=0.80,  out=4.00,  cache_read=0.08, cache_write_5m=1.00,  cache_write_1h=1.60),
}


def normalize_model(m: str | None) -> str:
    if not m:
        return "unknown"
    parts = m.split("-")
    if parts and parts[-1].isdigit() and len(parts[-1]) == 8:
        return "-".join(parts[:-1])
    return m


def cost(model: str, inp: int, out: int, cache_read: int, cw5: int, cw1h: int) -> float:
    p = PRICING.get(model)
    if not p:
        return 0.0
    return (
        inp * p["inp"] + out * p["out"] + cache_read * p["cache_read"]
        + cw5 * p["cache_write_5m"] + cw1h * p["cache_write_1h"]
    ) / 1_000_000


def main() -> None:
    ap = argparse.ArgumentParser(description="Claude Code usage + list-price cost over a window.")
    ap.add_argument("--days", type=float, default=1.0,
                    help="window size in days (fractional ok; default 1)")
    ap.add_argument("--top", type=int, default=15,
                    help="top N sessions by cost to show (default 15)")
    ap.add_argument("--no-per-day", action="store_true", help="omit per-day breakdown")
    ap.add_argument("--no-top", action="store_true", help="omit top-sessions table")
    args = ap.parse_args()

    cutoff = time.time() - args.days * 24 * 3600
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        raise SystemExit(f"no projects dir at {projects_dir}")

    sessions: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: dict(inp=0, out=0, cache_read=0, cw5=0, cw1h=0, msgs=0))
    )
    session_meta: dict[str, tuple[str, float, float]] = {}
    per_day: dict[str, float] = defaultdict(float)
    per_project: dict[str, dict] = defaultdict(lambda: dict(cost=0.0, msgs=0, sessions=set()))

    for jsonl in projects_dir.rglob("*.jsonl"):
        try:
            if jsonl.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        sid = jsonl.stem
        rel = jsonl.relative_to(projects_dir)
        project = rel.parts[0]
        try:
            fh = open(jsonl, errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if d.get("type") != "assistant":
                    continue
                msg = d.get("message", {}) or {}
                u = msg.get("usage", {}) or {}
                if not u:
                    continue
                ts = d.get("timestamp")
                ts_epoch = 0.0
                if ts:
                    try:
                        ts_epoch = datetime.fromisoformat(
                            ts.replace("Z", "+00:00")
                        ).timestamp()
                    except (ValueError, TypeError):
                        pass
                if ts_epoch < cutoff:
                    # Strict in-window accounting: per-day, per-project, and
                    # per-session totals all include only messages whose
                    # timestamp falls inside the window. Without this, a
                    # long-running session that started before the window
                    # would inflate its in-window cost.
                    continue

                model = normalize_model(msg.get("model"))
                cw = u.get("cache_creation", {}) or {}
                inp = u.get("input_tokens") or 0
                out = u.get("output_tokens") or 0
                cr = u.get("cache_read_input_tokens") or 0
                cw5 = cw.get("ephemeral_5m_input_tokens") or 0
                cw1h = cw.get("ephemeral_1h_input_tokens") or 0
                c = sessions[sid][model]
                c["inp"] += inp; c["out"] += out; c["cache_read"] += cr
                c["cw5"] += cw5; c["cw1h"] += cw1h; c["msgs"] += 1

                line_cost = cost(model, inp, out, cr, cw5, cw1h)
                day = datetime.fromtimestamp(ts_epoch, tz=timezone.utc).strftime("%Y-%m-%d")
                per_day[day] += line_cost

                prev = session_meta.get(sid)
                if prev is None:
                    session_meta[sid] = (project, ts_epoch, ts_epoch)
                else:
                    first = min(prev[1], ts_epoch) if prev[1] else ts_epoch
                    last = max(prev[2], ts_epoch)
                    session_meta[sid] = (project, first, last)

                per_project[project]["sessions"].add(sid)
                per_project[project]["msgs"] += 1
                per_project[project]["cost"] += line_cost

    recent_rows = []
    total_cost = 0.0
    total_msgs = 0
    totals = dict(inp=0, out=0, cache_read=0, cw5=0, cw1h=0)
    for sid, models in sessions.items():
        meta = session_meta.get(sid, (None, 0.0, 0.0))
        if meta[2] < cutoff:
            continue
        sc = 0.0
        sm = 0
        for model, c in models.items():
            sc += cost(model, c["inp"], c["out"], c["cache_read"], c["cw5"], c["cw1h"])
            sm += c["msgs"]
            for k in ("inp", "out", "cache_read", "cw5", "cw1h"):
                totals[k] += c[k]
        recent_rows.append((sc, sid, meta, sm))
        total_cost += sc
        total_msgs += sm
    recent_rows.sort(reverse=True)

    now_utc = datetime.now(timezone.utc)
    print(f"Window: {args.days:g} days ending {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print(
        f"Sessions: {len(recent_rows)}    "
        f"Assistant messages: {total_msgs}    "
        f"TOTAL list cost: ${total_cost:,.2f}"
    )

    if per_day and not args.no_per_day:
        print("\n=== Per-day (UTC) ===")
        peak = max(per_day.values()) if per_day else 0.0
        for day in sorted(per_day.keys()):
            bar_len = int(per_day[day] / peak * 40) if peak else 0
            print(f"  {day}  ${per_day[day]:>9,.2f}  {'█' * bar_len}")

    print("\n=== Per-project ===")
    proj_rows = sorted(per_project.items(), key=lambda kv: -kv[1]["cost"])
    print(f"  {'project':<55} {'sess':>5} {'msgs':>7} {'cost USD':>12}")
    for p, v in proj_rows:
        print(f"  {p[-53:]:<55} {len(v['sessions']):>5} {v['msgs']:>7} {v['cost']:>12,.2f}")

    if recent_rows and not args.no_top:
        n = min(args.top, len(recent_rows))
        print(f"\n=== Top {n} sessions by cost ===")
        print(f"  {'sess':<10} {'project':<40} {'start UTC':<17} {'msgs':>5} {'cost':>9}")
        for sc, sid, meta, sm in recent_rows[:n]:
            proj = (meta[0] or "?")[-38:]
            start = (
                datetime.fromtimestamp(meta[1], tz=timezone.utc).strftime("%m-%d %H:%M")
                if meta[1] else "?"
            )
            print(f"  {sid[:8]:<10} {proj:<40} {start:<17} {sm:>5} {sc:>9.2f}")

    print(f"\n=== Token totals ({args.days:g}d) ===")
    print(f"  input (uncached):       {totals['inp']:>15,}")
    print(f"  output:                 {totals['out']:>15,}")
    print(f"  cache read:             {totals['cache_read']:>15,}")
    print(f"  cache write 5m:         {totals['cw5']:>15,}")
    print(f"  cache write 1h:         {totals['cw1h']:>15,}")
    print()
    print("List-price reference: Opus $15/$75/$1.50 (in/out/cache-read), $18.75 5m write,")
    print("$30 1h write per 1M. Sonnet $3/$15/$0.30 ($3.75/$6 writes). Haiku $0.80/$4/")
    print("$0.08 ($1/$1.60). On Pro/Max plans actual billing is the subscription.")


if __name__ == "__main__":
    main()
