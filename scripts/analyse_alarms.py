#!/usr/bin/env python3
"""
Alarm Performance Analyser
==========================
Benchmarks an alarm & event export against the published performance targets in
ANSI/ISA-18.2 and EEMUA 191, and produces a self-contained HTML report.

Dependency-free: standard library only. Runs anywhere Python 3.8+ runs, including
locked-down plant networks where `pip install` is not an option.

Usage:
    python analyse_alarms.py <input.csv> [-o report.html] [--console-count N]
                             [--site "Plant name"] [--json summary.json]

The analyser auto-detects common column namings from Rockwell FactoryTalk,
Siemens PCS 7, ABB 800xA, Yokogawa and generic historian exports. If detection
fails it tells you which columns it found rather than guessing silently, because
a wrong column mapping produces a confident, wrong report.
"""

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

# ---------------------------------------------------------------------------
# Published benchmarks. Sources are cited in references/benchmarks.md.
# These are the targets the report scores against - they are not invented.
# ---------------------------------------------------------------------------
BENCH = {
    "per_day_target": 150,        # ISA-18.2: "very likely acceptable"
    "per_day_max": 300,           # ISA-18.2: "maximum manageable"
    "per_hour_target": 6,
    "per_hour_max": 12,
    "per_10min_target": 1,
    "per_10min_max": 2,
    "flood_threshold": 10,        # >10 alarms in a 10-min window = flood
    "flood_pct_target": 1.0,      # <1% of 10-min periods should be in flood
    "stale_hours": 24,
    "stale_count_target": 5,      # <5 stale on any given day
    "chatter_per_min": 3,         # 3+ activations of one tag within 60s
    "top10_load_target": 5.0,     # top 10 tags should be <~5% of total load
    "min_days_data": 30,          # ISA-18.2: assess on >=30 days
}

# Column detection. Order matters - first match wins.
COLUMN_HINTS = {
    "timestamp": ["timestamp", "time_stamp", "event_time", "eventtime", "datetime",
                  "date_time", "occurred", "event date", "datetime", "time", "date"],
    "tag":       ["tag", "tagname", "tag_name", "point", "pointname", "source",
                  "alarm_tag", "identifier", "item", "name"],
    "priority":  ["priority", "severity", "prio", "alarm_priority", "class",
                  "alarmclass", "urgency"],
    "event":     ["event", "eventtype", "event_type", "condition", "state",
                  "transition", "action", "status", "alarm_state"],
    "desc":      ["description", "message", "desc", "text", "alarm_text", "comment"],
    "console":   ["console", "operator", "area", "unit", "workstation", "position",
                  "operating_position", "zone"],
}

TS_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M", "%m/%d/%Y %I:%M:%S %p", "%d %b %Y %H:%M:%S",
]

ALARM_WORDS = {"alm", "alarm", "active", "in alarm", "raised", "on", "set",
               "activated", "trip", "hi", "hihi", "lo", "lolo", "fault", "true"}
RETURN_WORDS = {"rtn", "return", "normal", "cleared", "clear", "off", "reset",
                "inactive", "ok", "false", "returned to normal"}
ACK_WORDS = {"ack", "acknowledge", "acknowledged", "ackd"}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def detect_columns(header):
    """Map logical fields to actual header names."""
    norm = {h: re.sub(r"[^a-z0-9 ]", "", h.strip().lower()) for h in header}
    mapping = {}
    for field, hints in COLUMN_HINTS.items():
        for hint in hints:
            for original, cleaned in norm.items():
                if original in mapping.values():
                    continue
                if cleaned == hint or cleaned.replace(" ", "") == hint.replace(" ", ""):
                    mapping[field] = original
                    break
            if field in mapping:
                break
    # second pass: substring match for anything still missing
    for field, hints in COLUMN_HINTS.items():
        if field in mapping:
            continue
        for hint in hints:
            for original, cleaned in norm.items():
                if original in mapping.values():
                    continue
                if hint in cleaned:
                    mapping[field] = original
                    break
            if field in mapping:
                break
    return mapping


def parse_ts(value):
    v = (value or "").strip()
    if not v:
        return None
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(v.replace("Z", "").split("+")[0])
    except Exception:
        return None


def classify_event(value):
    v = (value or "").strip().lower()
    if not v:
        return "alarm"          # export with no event column = one row per alarm
    if any(w == v or w in v for w in ACK_WORDS):
        return "ack"
    if any(w == v or w in v for w in RETURN_WORDS):
        return "return"
    if any(w == v or w in v for w in ALARM_WORDS):
        return "alarm"
    return "alarm"


def normalise_priority(value):
    v = (value or "").strip().lower()
    if not v:
        return "unassigned"
    if v.isdigit():
        n = int(v)
        if n <= 1:
            return "high"
        if n == 2:
            return "medium"
        return "low"
    for key, out in [("emerg", "high"), ("crit", "high"), ("high", "high"),
                     ("urgent", "high"), ("med", "medium"), ("warn", "medium"),
                     ("low", "low"), ("advis", "low"), ("info", "low"),
                     ("journal", "low"), ("diag", "low")]:
        if key in v:
            return out
    return "unassigned"


def load(path):
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(fh, dialect=dialect)
        header = reader.fieldnames or []
        cols = detect_columns(header)
        if "timestamp" not in cols or "tag" not in cols:
            raise SystemExit(
                "Could not identify a timestamp and tag column.\n"
                "  Columns found : {}\n"
                "  Mapped so far : {}\n"
                "Rename the relevant columns (e.g. 'Timestamp', 'Tag', 'Priority', "
                "'EventType') and re-run. The analyser refuses to guess, because a "
                "wrong mapping produces a confident, wrong report.".format(header, cols)
            )
        rows, skipped = [], 0
        for raw in reader:
            ts = parse_ts(raw.get(cols["timestamp"]))
            tag = (raw.get(cols["tag"]) or "").strip()
            if ts is None or not tag:
                skipped += 1
                continue
            rows.append({
                "ts": ts,
                "tag": tag,
                "priority": normalise_priority(raw.get(cols.get("priority", ""), "")),
                "event": classify_event(raw.get(cols.get("event", ""), "")),
                "desc": (raw.get(cols.get("desc", ""), "") or "").strip()[:160],
                "console": (raw.get(cols.get("console", ""), "") or "").strip(),
            })
    rows.sort(key=lambda r: r["ts"])
    return rows, cols, skipped


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def analyse(rows, console_count=None):
    alarms = [r for r in rows if r["event"] == "alarm"]
    if not alarms:
        raise SystemExit("No alarm activations found after parsing. Check the event/state column.")

    start, end = alarms[0]["ts"], alarms[-1]["ts"]
    span_hours = max((end - start).total_seconds() / 3600.0, 1 / 60.0)
    span_days = max(span_hours / 24.0, 1e-9)

    consoles = set(r["console"] for r in rows if r["console"])
    n_consoles = console_count or (len(consoles) if consoles else 1)

    total = len(alarms)
    per_day = total / span_days / n_consoles
    per_hour = total / span_hours / n_consoles

    # --- 10-minute windows -------------------------------------------------
    buckets = Counter()
    for r in alarms:
        buckets[int(r["ts"].timestamp() // 600)] += 1
    first_b = int(start.timestamp() // 600)
    last_b = int(end.timestamp() // 600)
    total_windows = max(last_b - first_b + 1, 1)
    counts = [buckets.get(b, 0) for b in range(first_b, last_b + 1)]
    flood_windows = sum(1 for c in counts if c > BENCH["flood_threshold"])
    flood_pct = flood_windows / total_windows * 100.0
    peak_10min = max(counts) if counts else 0
    per_10min_avg = total / (span_hours * 6) / n_consoles

    # contiguous flood episodes
    episodes, run = [], None
    for i, c in enumerate(counts):
        if c > BENCH["flood_threshold"]:
            if run is None:
                run = {"start_idx": i, "peak": c, "alarms": c}
            else:
                run["peak"] = max(run["peak"], c)
                run["alarms"] += c
        elif run is not None:
            run["end_idx"] = i - 1
            episodes.append(run)
            run = None
    if run is not None:
        run["end_idx"] = len(counts) - 1
        episodes.append(run)
    for ep in episodes:
        ep["start"] = datetime.fromtimestamp((first_b + ep["start_idx"]) * 600)
        ep["minutes"] = (ep["end_idx"] - ep["start_idx"] + 1) * 10
    episodes.sort(key=lambda e: e["alarms"], reverse=True)

    # --- bad actors --------------------------------------------------------
    tag_counts = Counter(r["tag"] for r in alarms)
    tag_desc, tag_prio = {}, {}
    for r in alarms:
        tag_desc.setdefault(r["tag"], r["desc"])
        tag_prio.setdefault(r["tag"], r["priority"])
    ranked = tag_counts.most_common()
    top10_load = sum(c for _, c in ranked[:10]) / total * 100.0
    top20 = [{
        "tag": t, "count": c, "pct": c / total * 100.0,
        "per_day": c / span_days,
        "desc": tag_desc.get(t, ""), "priority": tag_prio.get(t, "unassigned"),
    } for t, c in ranked[:20]]

    # --- chattering --------------------------------------------------------
    by_tag = defaultdict(list)
    for r in alarms:
        by_tag[r["tag"]].append(r["ts"])
    chattering = []
    for tag, stamps in by_tag.items():
        if len(stamps) < BENCH["chatter_per_min"]:
            continue
        stamps.sort()
        worst, j = 0, 0
        for i in range(len(stamps)):
            while (stamps[i] - stamps[j]).total_seconds() > 60:
                j += 1
            worst = max(worst, i - j + 1)
        if worst >= BENCH["chatter_per_min"]:
            chattering.append({"tag": tag, "burst": worst, "total": len(stamps),
                               "desc": tag_desc.get(tag, "")})
    chattering.sort(key=lambda c: (-c["burst"], -c["total"]))

    # --- stale -------------------------------------------------------------
    open_since, stale = {}, []
    for r in rows:
        if r["event"] == "alarm":
            open_since.setdefault(r["tag"], r["ts"])
        elif r["event"] == "return" and r["tag"] in open_since:
            dur = (r["ts"] - open_since[r["tag"]]).total_seconds() / 3600.0
            if dur >= BENCH["stale_hours"]:
                stale.append({"tag": r["tag"], "hours": dur,
                              "desc": tag_desc.get(r["tag"], "")})
            del open_since[r["tag"]]
    for tag, since in open_since.items():
        dur = (end - since).total_seconds() / 3600.0
        if dur >= BENCH["stale_hours"]:
            stale.append({"tag": tag, "hours": dur, "desc": tag_desc.get(tag, ""),
                          "still_open": True})
    stale.sort(key=lambda s: -s["hours"])

    # --- priority ----------------------------------------------------------
    pri = Counter(r["priority"] for r in alarms)
    pri_pct = dict((k, pri.get(k, 0) / total * 100.0)
                   for k in ("high", "medium", "low", "unassigned"))

    # --- series ------------------------------------------------------------
    daily = Counter(r["ts"].date() for r in alarms)
    day_series = [{"date": d.isoformat(), "count": daily[d] / n_consoles}
                  for d in sorted(daily)]
    hourly = Counter(r["ts"].hour for r in alarms)
    hour_profile = [hourly.get(h, 0) for h in range(24)]

    return {
        "meta": {
            "start": start.isoformat(sep=" ", timespec="seconds"),
            "end": end.isoformat(sep=" ", timespec="seconds"),
            "span_days": span_days, "span_hours": span_hours,
            "consoles": n_consoles, "total_activations": total,
            "total_rows": len(rows),
            "sufficient_data": span_days >= BENCH["min_days_data"],
        },
        "rates": {
            "per_day": per_day, "per_hour": per_hour, "per_10min": per_10min_avg,
            "peak_10min": peak_10min, "flood_pct": flood_pct,
            "flood_windows": flood_windows, "total_windows": total_windows,
        },
        "episodes": episodes[:10],
        "top20": top20, "top10_load": top10_load,
        "chattering": chattering[:20], "chattering_total": len(chattering),
        "stale": stale[:20], "stale_total": len(stale),
        "priority": pri_pct, "priority_counts": dict(pri),
        "day_series": day_series, "hour_profile": hour_profile,
        "unique_tags": len(tag_counts),
    }


def score(a):
    """Traffic-light each metric against the published target."""
    r, out = a["rates"], {}

    def band(value, target, maximum):
        if value <= target:
            return "good"
        if value <= maximum:
            return "warn"
        return "bad"

    out["per_day"] = band(r["per_day"], BENCH["per_day_target"], BENCH["per_day_max"])
    out["per_hour"] = band(r["per_hour"], BENCH["per_hour_target"], BENCH["per_hour_max"])
    out["per_10min"] = band(r["per_10min"], BENCH["per_10min_target"], BENCH["per_10min_max"])
    out["flood_pct"] = "good" if r["flood_pct"] < BENCH["flood_pct_target"] else (
        "warn" if r["flood_pct"] < 5 else "bad")
    out["chattering"] = "good" if a["chattering_total"] == 0 else (
        "warn" if a["chattering_total"] <= 5 else "bad")
    out["stale"] = "good" if a["stale_total"] < BENCH["stale_count_target"] else (
        "warn" if a["stale_total"] < 15 else "bad")
    out["top10_load"] = "good" if a["top10_load"] <= BENCH["top10_load_target"] else (
        "warn" if a["top10_load"] <= 20 else "bad")
    hi = a["priority"]["high"]
    out["priority"] = "good" if hi <= 8 else ("warn" if hi <= 20 else "bad")
    return out


# ---------------------------------------------------------------------------
# Rendering - inline SVG so the report is a single portable file
# ---------------------------------------------------------------------------
def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bar_chart(series, labels, width=920, height=190, target=None, maximum=None):
    if not series:
        return ""
    n = len(series)
    top = max(max(series), (maximum or 0), (target or 0)) * 1.15 or 1
    bw = width / n
    bars = []
    for i, v in enumerate(series):
        h = (v / top) * height
        x = i * bw
        colour = "var(--good)"
        if maximum and v > maximum:
            colour = "var(--bad)"
        elif target and v > target:
            colour = "var(--warn)"
        bars.append(
            '<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" fill="{}" opacity=".85">'
            '<title>{}: {:.0f}</title></rect>'.format(
                x, height - h, max(bw - 1.5, 1), h, colour, esc(labels[i]), v))
    lines = []
    for val, cls in [(target, "tline"), (maximum, "mline")]:
        if val:
            y = height - (val / top) * height
            lines.append('<line x1="0" y1="{:.1f}" x2="{}" y2="{:.1f}" class="{}"/>'.format(y, width, y, cls))
            lines.append('<text x="{}" y="{:.1f}" class="glab" text-anchor="end">{:g}</text>'.format(width - 4, y - 5, val))
    step = max(1, n // 12)
    ticks = "".join(
        '<text x="{:.1f}" y="{}" class="tick" text-anchor="middle">{}</text>'.format(
            i * bw + bw / 2, height + 15, esc(labels[i]))
        for i in range(0, n, step))
    return ('<svg viewBox="0 0 {} {}" class="chart" preserveAspectRatio="none">'.format(width, height + 22)
            + "".join(bars) + "".join(lines) + ticks + "</svg>")


def donut(pri):
    order = [("low", "var(--good)"), ("medium", "var(--warn)"),
             ("high", "var(--bad)"), ("unassigned", "var(--muted)")]
    total = sum(max(pri.get(k, 0), 0) for k, _ in order) or 1
    r = 54
    c = 2 * math.pi * r
    off, segs = 0.0, []
    for key, colour in order:
        frac = max(pri.get(key, 0), 0) / total
        if frac <= 0:
            continue
        segs.append(
            '<circle cx="70" cy="70" r="{}" fill="none" stroke="{}" stroke-width="20" '
            'stroke-dasharray="{:.2f} {:.2f}" stroke-dashoffset="{:.2f}" '
            'transform="rotate(-90 70 70)"><title>{}: {:.1f}%</title></circle>'.format(
                r, colour, frac * c, c, -off * c, key, pri.get(key, 0)))
        off += frac
    return '<svg viewBox="0 0 140 140" class="donut">{}</svg>'.format("".join(segs))


def metric_card(label, value, unit, target_text, state):
    return ('<div class="m {}"><div class="ml">{}</div>'
            '<div class="mv">{}<span class="mu">{}</span></div>'
            '<div class="mt">{}</div></div>').format(state, esc(label), esc(value), esc(unit), target_text)


def render(a, s, site, source_name):
    r, m = a["rates"], a["meta"]
    day_vals = [d["count"] for d in a["day_series"]]
    day_labs = [d["date"][5:] for d in a["day_series"]]

    findings = []
    if s["per_day"] != "good":
        findings.append(
            "Operators are receiving <strong>{:.0f} alarms per day</strong> against an ISA-18.2 "
            "'very likely acceptable' figure of {} and a maximum manageable figure of {}. "
            "That is {:.1f}&times; the acceptable load.".format(
                r["per_day"], BENCH["per_day_target"], BENCH["per_day_max"],
                r["per_day"] / BENCH["per_day_target"]))
    if s["flood_pct"] != "good":
        findings.append(
            "<strong>{:.1f}% of all ten-minute periods</strong> exceeded {} alarms &mdash; the flood "
            "threshold. ISA-18.2 targets under {:g}%. Peak observed was <strong>{} alarms in ten "
            "minutes</strong>.".format(r["flood_pct"], BENCH["flood_threshold"],
                                       BENCH["flood_pct_target"], r["peak_10min"]))
    if s["top10_load"] != "good":
        findings.append(
            "The <strong>top ten tags alone generate {:.1f}% of total alarm load</strong>. Concentration "
            "this high is good news operationally &mdash; it means a small, bounded remediation list "
            "addresses most of the burden.".format(a["top10_load"]))
    if a["chattering_total"]:
        findings.append(
            "<strong>{} tags are chattering</strong> &mdash; activating {} or more times within a single "
            "minute. ISA-18.2 targets zero.".format(a["chattering_total"], BENCH["chatter_per_min"]))
    if a["stale_total"]:
        findings.append(
            "<strong>{} alarms stood active for over {} hours.</strong> ISA-18.2 targets fewer than {} on "
            "any given day. Standing alarms train operators to ignore the annunciator.".format(
                a["stale_total"], BENCH["stale_hours"], BENCH["stale_count_target"]))
    if s["priority"] != "good":
        findings.append(
            "Priority distribution is <strong>{:.0f}% high / {:.0f}% medium / {:.0f}% low</strong> against "
            "the ISA-18.2 guide of 5 / 15 / 80. When everything is urgent, nothing is.".format(
                a["priority"]["high"], a["priority"]["medium"], a["priority"]["low"]))
    if not findings:
        findings.append("This alarm system meets the published ISA-18.2 and EEMUA 191 performance targets "
                        "on every metric assessed. That is genuinely uncommon.")

    rows_top = "".join(
        '<tr><td class="rank">{}</td><td class="tag">{}</td><td class="d">{}</td>'
        '<td class="n">{:,}</td><td class="n">{:.1f}</td><td class="n">{:.2f}%</td>'
        '<td><span class="pill p-{}">{}</span></td></tr>'.format(
            i + 1, esc(t["tag"]), esc(t["desc"]) or "&mdash;", t["count"], t["per_day"],
            t["pct"], t["priority"], t["priority"])
        for i, t in enumerate(a["top20"]))

    rows_chat = "".join(
        '<tr><td class="tag">{}</td><td class="d">{}</td><td class="n">{}</td>'
        '<td class="n">{:,}</td></tr>'.format(
            esc(c["tag"]), esc(c["desc"]) or "&mdash;", c["burst"], c["total"])
        for c in a["chattering"]) or '<tr><td colspan="4" class="none">No chattering alarms detected.</td></tr>'

    rows_stale = "".join(
        '<tr><td class="tag">{}</td><td class="d">{}</td><td class="n">{:.1f} h</td>'
        '<td class="n">{}</td></tr>'.format(
            esc(st["tag"]), esc(st["desc"]) or "&mdash;", st["hours"],
            "still active" if st.get("still_open") else "cleared")
        for st in a["stale"]) or '<tr><td colspan="4" class="none">No stale alarms detected.</td></tr>'

    rows_ep = "".join(
        '<tr><td class="n">{:%Y-%m-%d %H:%M}</td><td class="n">{} min</td>'
        '<td class="n">{:,}</td><td class="n">{}</td></tr>'.format(
            e["start"], e["minutes"], e["alarms"], e["peak"])
        for e in a["episodes"]) or '<tr><td colspan="4" class="none">No flood episodes detected.</td></tr>'

    warn_data = "" if m["sufficient_data"] else (
        '<div class="warnbox"><strong>Assessment window is {:.1f} days.</strong> ISA-18.2 recommends at '
        'least {} days of data before drawing conclusions about alarm system performance. Treat these '
        'figures as indicative, not as a baseline of record.</div>'.format(
            m["span_days"], BENCH["min_days_data"]))

    css = """
:root{--bg:#fbfbfc;--card:#fff;--ink:#14161a;--dim:#5b6068;--faint:#8b9099;
--line:#e4e6ea;--good:#1d9a6c;--warn:#d98324;--bad:#cf3d4f;--muted:#b3b8c0;
--mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:400 15px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Inter,sans-serif;}
.wrap{max-width:1040px;margin:0 auto;padding:44px 28px 80px}
header{border-bottom:2px solid var(--ink);padding-bottom:22px;margin-bottom:34px}
.kicker{font:500 11px/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--faint);margin-bottom:12px}
h1{font-size:31px;margin:0 0 10px;letter-spacing:-.02em;font-weight:600}
.sub{color:var(--dim);font-size:14px;margin:0}
.sub b{color:var(--ink);font-weight:500}
h2{font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);
margin:46px 0 16px;font-weight:600;border-top:1px solid var(--line);padding-top:20px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.m{background:var(--card);border:1px solid var(--line);border-left-width:3px;border-radius:6px;padding:16px 16px 14px}
.m.good{border-left-color:var(--good)} .m.warn{border-left-color:var(--warn)} .m.bad{border-left-color:var(--bad)}
.ml{font:500 10.5px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--faint);margin-bottom:9px}
.mv{font:600 26px/1 var(--mono);letter-spacing:-.02em}
.m.good .mv{color:var(--good)} .m.warn .mv{color:var(--warn)} .m.bad .mv{color:var(--bad)}
.mu{font-size:12px;font-weight:400;color:var(--faint);margin-left:4px}
.mt{font-size:11.5px;color:var(--faint);margin-top:8px;line-height:1.45}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:20px 22px}
.findings{padding-left:20px;margin:0}
.findings li{margin-bottom:12px;color:var(--dim)}
.findings li strong{color:var(--ink);font-weight:600}
.chart{width:100%;height:auto;display:block;margin-top:6px}
.tline{stroke:var(--good);stroke-width:1;stroke-dasharray:4 3}
.mline{stroke:var(--bad);stroke-width:1;stroke-dasharray:4 3}
.glab{font:500 9px var(--mono);fill:var(--faint)}
.tick{font:400 8.5px var(--mono);fill:var(--faint)}
table{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--card)}
th{text-align:left;font:500 10px var(--mono);letter-spacing:.11em;text-transform:uppercase;
color:var(--faint);padding:11px 12px;border-bottom:1px solid var(--line)}
td{padding:10px 12px;border-bottom:1px solid var(--line);color:var(--dim);vertical-align:top}
tr:last-child td{border-bottom:none}
td.n,th.n{font-family:var(--mono);white-space:nowrap;text-align:right}
td.rank{font-family:var(--mono);color:var(--faint);width:30px}
td.tag{font-family:var(--mono);color:var(--ink);font-size:12.5px;white-space:nowrap}
td.d{font-size:12.5px}
td.none{text-align:center;color:var(--faint);padding:22px}
.tbl{border:1px solid var(--line);border-radius:6px;overflow:hidden;overflow-x:auto}
.pill{font:500 10px var(--mono);padding:2px 7px;border-radius:3px;text-transform:uppercase}
.p-high{background:#fdeaec;color:var(--bad)} .p-medium{background:#fdf2e3;color:var(--warn)}
.p-low{background:#e8f5ef;color:var(--good)} .p-unassigned{background:#eef0f2;color:var(--faint)}
.split{display:grid;grid-template-columns:180px 1fr;gap:26px;align-items:center}
.donut{width:140px;height:140px}
.leg{font-size:13px;color:var(--dim);margin:0;padding:0;list-style:none}
.leg li{margin-bottom:7px;display:flex;align-items:center;gap:9px}
.sw{width:10px;height:10px;border-radius:2px;flex:none}
.leg b{font-family:var(--mono);color:var(--ink);font-weight:600}
.warnbox{background:#fdf2e3;border:1px solid #f0d9b5;border-radius:6px;padding:14px 16px;
font-size:13.5px;color:#7a4d12;margin-bottom:20px}
.scope{background:#f2f4f6;border:1px solid var(--line);border-radius:6px;padding:20px 22px;margin-top:26px}
.scope h3{font-size:13px;margin:0 0 10px;letter-spacing:.04em}
.scope p{font-size:13.5px;color:var(--dim);margin:0 0 10px}
.scope p:last-child{margin:0}
footer{margin-top:52px;padding-top:20px;border-top:1px solid var(--line);
font-size:12px;color:var(--faint);line-height:1.7}
@media(max-width:860px){.grid{grid-template-columns:repeat(2,1fr)}.split{grid-template-columns:1fr}}
@media print{body{background:#fff}.wrap{padding:0}}
"""

    cards = "".join([
        metric_card("Alarms / day / position", "{:.0f}".format(r["per_day"]), "",
                    "Target &le;{} &middot; max manageable {}".format(BENCH["per_day_target"], BENCH["per_day_max"]), s["per_day"]),
        metric_card("Alarms / hour", "{:.1f}".format(r["per_hour"]), "",
                    "Target &le;{} &middot; max {}".format(BENCH["per_hour_target"], BENCH["per_hour_max"]), s["per_hour"]),
        metric_card("Peak in 10 min", str(r["peak_10min"]), "",
                    "Flood threshold is {}".format(BENCH["flood_threshold"]),
                    "bad" if r["peak_10min"] > BENCH["flood_threshold"] * 3 else s["flood_pct"]),
        metric_card("Time in flood", "{:.1f}".format(r["flood_pct"]), "%",
                    "Target &lt;{:g}% of 10-min periods".format(BENCH["flood_pct_target"]), s["flood_pct"]),
        metric_card("Chattering tags", str(a["chattering_total"]), "",
                    "ISA-18.2 target is 0", s["chattering"]),
        metric_card("Stale alarms", str(a["stale_total"]), "",
                    "Target &lt;{} on any day (&gt;{} h active)".format(BENCH["stale_count_target"], BENCH["stale_hours"]), s["stale"]),
        metric_card("Top 10 tag load", "{:.1f}".format(a["top10_load"]), "%",
                    "Target &le;{:g}% of total load".format(BENCH["top10_load_target"]), s["top10_load"]),
        metric_card("High priority", "{:.0f}".format(a["priority"]["high"]), "%",
                    "ISA-18.2 guide: 5% high / 15% med / 80% low", s["priority"]),
    ])

    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alarm Performance Assessment &mdash; {site}</title>
<style>{css}</style></head><body><div class="wrap">

<header>
  <div class="kicker">Alarm system performance assessment</div>
  <h1>{site}</h1>
  <p class="sub">Assessed against <b>ANSI/ISA-18.2</b> and <b>EEMUA 191</b> published targets &nbsp;&middot;&nbsp;
  {start} to {end} &nbsp;&middot;&nbsp; <b>{days:.1f}</b> days &nbsp;&middot;&nbsp;
  <b>{total:,}</b> activations across <b>{tags:,}</b> unique tags &nbsp;&middot;&nbsp;
  <b>{consoles}</b> operating position{plural}<br>
  Source: <b>{source}</b></p>
</header>

{warn_data}

<h2>Headline metrics</h2>
<div class="grid">{cards}</div>

<h2>What this means</h2>
<div class="card"><ul class="findings">{findings}</ul></div>

<h2>Daily alarm rate per operating position</h2>
<div class="card">{daychart}
<p class="mt" style="margin-top:12px">Green dashed line: ISA-18.2 acceptable ({pdt}/day). Red dashed: maximum manageable ({pdm}/day).</p></div>

<h2>Alarm load by hour of day</h2>
<div class="card">{hourchart}
<p class="mt" style="margin-top:12px">Total activations per clock hour across the whole window. Sharp peaks usually indicate shift changes, batch steps or scheduled equipment starts &mdash; often the cheapest things to rationalise first.</p></div>

<h2>Priority distribution</h2>
<div class="card"><div class="split">{donut}
<ul class="leg">
  <li><span class="sw" style="background:var(--good)"></span>Low &nbsp;<b>{plow:.1f}%</b> <span style="color:var(--faint)">(guide 80%)</span></li>
  <li><span class="sw" style="background:var(--warn)"></span>Medium &nbsp;<b>{pmed:.1f}%</b> <span style="color:var(--faint)">(guide 15%)</span></li>
  <li><span class="sw" style="background:var(--bad)"></span>High &nbsp;<b>{phigh:.1f}%</b> <span style="color:var(--faint)">(guide 5%)</span></li>
  <li><span class="sw" style="background:var(--muted)"></span>Unassigned &nbsp;<b>{puna:.1f}%</b></li>
</ul></div></div>

<h2>Top 20 bad actors</h2>
<div class="tbl"><table>
<thead><tr><th></th><th>Tag</th><th>Description</th><th class="n">Activations</th><th class="n">Per day</th><th class="n">% of load</th><th>Priority</th></tr></thead>
<tbody>{rows_top}</tbody></table></div>

<h2>Chattering alarms <span style="color:var(--faint);font-weight:400;text-transform:none;letter-spacing:0">&mdash; {cpm}+ activations within 60 seconds</span></h2>
<div class="tbl"><table>
<thead><tr><th>Tag</th><th>Description</th><th class="n">Worst burst / min</th><th class="n">Total</th></tr></thead>
<tbody>{rows_chat}</tbody></table></div>

<h2>Stale alarms <span style="color:var(--faint);font-weight:400;text-transform:none;letter-spacing:0">&mdash; active longer than {sh} hours</span></h2>
<div class="tbl"><table>
<thead><tr><th>Tag</th><th>Description</th><th class="n">Duration</th><th class="n">State</th></tr></thead>
<tbody>{rows_stale}</tbody></table></div>

<h2>Largest flood episodes</h2>
<div class="tbl"><table>
<thead><tr><th class="n">Started</th><th class="n">Duration</th><th class="n">Alarms</th><th class="n">Peak / 10 min</th></tr></thead>
<tbody>{rows_ep}</tbody></table></div>

<div class="scope">
  <h3>What this assessment does not do</h3>
  <p>This is a <strong>measurement</strong> of alarm system performance against published benchmarks. It is not a rationalisation, and it is not a compliance record.</p>
  <p>Deciding whether a specific alarm should be removed, re-ranged, re-prioritised, suppressed or made state-based requires the P&amp;IDs, the HAZOP and LOPA record, the defined operator action and consequence for each alarm, and the people who actually run the plant. Those decisions carry safety consequence and need a competent person who is accountable for them &mdash; and under ISA-18.2 and IEC 61511 the rationalisation record must be documented, reviewed and retained.</p>
  <p>Treat the bad-actor and chattering lists as a <strong>prioritised work queue</strong> for that exercise, not as its conclusion.</p>
</div>

<footer>
Generated by <strong>Alarm Performance Analyser</strong> &mdash; an open tool that benchmarks alarm &amp; event exports
against ANSI/ISA-18.2 and EEMUA 191 performance targets.<br>
Benchmark values are drawn from the published standards; see <code>references/benchmarks.md</code> for the figures
used and their sources. Metrics are computed from the supplied export only &mdash; accuracy depends on the completeness
of that export. ISA-18.2 recommends assessing performance over at least {mind} days.
</footer>

</div></body></html>""".format(
        site=esc(site), css=css, start=esc(m["start"]), end=esc(m["end"]),
        days=m["span_days"], total=m["total_activations"], tags=a["unique_tags"],
        consoles=m["consoles"], plural="s" if m["consoles"] != 1 else "",
        source=esc(source_name), warn_data=warn_data, cards=cards,
        findings="".join("<li>{}</li>".format(f) for f in findings),
        daychart=bar_chart(day_vals, day_labs, target=BENCH["per_day_target"], maximum=BENCH["per_day_max"]),
        hourchart=bar_chart(a["hour_profile"], ["{:02d}".format(h) for h in range(24)]),
        pdt=BENCH["per_day_target"], pdm=BENCH["per_day_max"],
        donut=donut(a["priority"]),
        plow=a["priority"]["low"], pmed=a["priority"]["medium"],
        phigh=a["priority"]["high"], puna=a["priority"]["unassigned"],
        rows_top=rows_top, rows_chat=rows_chat, rows_stale=rows_stale, rows_ep=rows_ep,
        cpm=BENCH["chatter_per_min"], sh=BENCH["stale_hours"], mind=BENCH["min_days_data"])


# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="Benchmark an alarm export against ISA-18.2 / EEMUA 191.")
    p.add_argument("input", help="Alarm & event export (CSV/TSV)")
    p.add_argument("-o", "--output", default="alarm_assessment.html")
    p.add_argument("--site", default="Unnamed site", help="Site or console name for the report header")
    p.add_argument("--console-count", type=int, default=None,
                   help="Number of operating positions the export covers (default: auto-detect, else 1)")
    p.add_argument("--json", dest="json_out", default=None, help="Also write raw metrics as JSON")
    args = p.parse_args()

    rows, cols, skipped = load(args.input)
    print("Parsed {:,} rows ({:,} skipped). Column mapping: {}".format(len(rows), skipped, cols))
    a = analyse(rows, args.console_count)
    s = score(a)

    src = args.input.replace("\\", "/").split("/")[-1]
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(render(a, s, args.site, src))
    print("Report written to {}".format(args.output))

    if args.json_out:
        payload = dict(a)
        payload["scores"] = s
        payload["benchmarks"] = BENCH
        for ep in payload.get("episodes", []):
            ep["start"] = ep["start"].isoformat(sep=" ", timespec="minutes")
            ep.pop("start_idx", None)
            ep.pop("end_idx", None)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        print("Metrics written to {}".format(args.json_out))

    r = a["rates"]
    print("\n  {:.0f} alarms/day/position (target {}) | {:.1f}% time in flood (target <{:g}%) "
          "| {} chattering | {} stale".format(
              r["per_day"], BENCH["per_day_target"], r["flood_pct"],
              BENCH["flood_pct_target"], a["chattering_total"], a["stale_total"]))


if __name__ == "__main__":
    main()
