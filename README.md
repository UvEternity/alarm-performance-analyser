# Alarm Performance Analyser

Benchmark an industrial alarm & event export against the published **ANSI/ISA-18.2** and **EEMUA 191** performance targets, and get back a single self-contained HTML report.

Free. Standard library only. No install, no account, no upload - it runs on your machine, including locked-down plant networks where `pip install` isn't an option.

---

## What it measures

| | |
|---|---|
| **Alarm rate** | Per day, per hour and per 10 minutes, **per operating position** — against the 150/300 acceptable/maximum figures |
| **Flood analysis** | Percentage of 10-minute periods exceeding 10 alarms, peak rate, and the largest contiguous flood episodes with duration and peak |
| **Bad actors** | Top 20 tags by activation count, with per-day rate and share of total load |
| **Chattering** | Tags activating 3+ times within any rolling 60 seconds |
| **Stale alarms** | Alarms standing active longer than 24 hours, including those never cleared |
| **Priority distribution** | Actual split against the ISA-18.2 guide of 80% low / 15% medium / 5% high |
| **Load profile** | Daily trend and hour-of-day distribution |

Every threshold comes from a published standard. [`references/benchmarks.md`](references/benchmarks.md) gives the figures, the sources, exactly how each metric is computed, and the known limitations. If a number looks wrong, you should be able to check it against your own copy of the standard — that's deliberate.

---

## Usage

```bash
python scripts/analyse_alarms.py your_export.csv \
    -o assessment.html \
    --site "Site Name Here" \
    --console-count 2 \
    --json metrics.json
```

Requires Python 3.8+. Nothing else.

> **Windows:** if `python` prints "Python was not found; run without arguments to install from the Microsoft Store", no real Python is installed yet — that message comes from a Store alias stub, not an error in this tool. Install Python from [python.org](https://www.python.org/downloads/) or `winget install Python.Python.3.12`, then reopen your terminal.

### Input

Any CSV or TSV alarm & event export. Column names are auto-detected across common vendor formats (Rockwell FactoryTalk, Siemens PCS 7, ABB 800xA, Yokogawa, Honeywell, AVEVA/Wonderware, generic historian).

| Column | Required | Notes |
|---|---|---|
| Timestamp | **yes** | Most common formats parsed automatically |
| Tag / point | **yes** | |
| Event type | recommended | Alarm / return / acknowledge. Without it, every row counts as an activation |
| Priority | recommended | Numeric or text schemes both handled |
| Description | optional | Makes the bad-actor table readable |
| Console / area | optional | Used to derive operating position count |

If detection fails the script stops and shows you what it found rather than guessing. A wrong column mapping produces a confident, wrong report — worse than an error.

### The one input that matters most

`--console-count` sets how many operating positions the export covers. **Every rate metric is per operator.** An export spanning four consoles analysed as one will understate operator load by a factor of four, which is the most common way alarm assessments end up flattering a site. If you're unsure, ask the control room before you quote a number.

### Try it without any real data

```bash
python scripts/make_demo_data.py -o demo_alarms.csv --days 45
python scripts/analyse_alarms.py demo_alarms.csv -o demo_report.html --site "Demo Concentrator"
```

The generator invents a plausible mineral processing plant with the usual pathologies built in. Everything it produces is synthetic. Don't present it as a real assessment.

---

## What this does *not* do

This is a **measurement** tool. It is not a rationalisation, and it does not produce a compliance record.

Deciding whether a specific alarm should be removed, re-ranged, re-prioritised, suppressed or made state-based needs the P&IDs, the HAZOP and LOPA record, the defined operator action and consequence for each alarm, and the people who run the plant. Those decisions carry safety consequence, they need a competent person accountable for them, and under ISA-18.2 and IEC 61511 the rationalisation record must be documented, reviewed and retained.

An alarm that looks like pure noise in an export can be the last line of protection on a scenario the export doesn't show you. **Treat the output as a prioritised work queue, not a conclusion.**

---

## A note on your data

Alarm histories are operational data and are often confidential. This tool reads a local file and writes a local file. It makes no network calls and sends nothing anywhere.

If you plan to share a report, note that tag names alone can identify a site and its process. The report layout stays readable after tag redaction.

---

## Licence

MIT. Use it, fork it

If it's useful, telling someone is appreciated. If it's wrong, telling *me* is more useful — corrections to the metric definitions especially.
