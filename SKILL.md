---
name: alarm-performance-analyser
description: Benchmark an industrial alarm & event export against the published ANSI/ISA-18.2 and EEMUA 191 performance targets, and produce an assessment report covering alarm rate per operator, flood analysis, bad actors, chattering, stale alarms and priority distribution. Use this whenever someone mentions alarm management, alarm rationalisation, alarm flooding, nuisance alarms, bad actor alarms, chattering alarms, standing or stale alarms, EEMUA 191, ISA-18.2, IEC 62682, alarm KPIs, operator alarm load, or shares an alarm/event export, alarm history, alarm log or SOE file from a DCS, SCADA or PLC system (Rockwell FactoryTalk, Siemens PCS 7, ABB 800xA, Yokogawa, Honeywell, Wonderware, AVEVA). Also use when someone asks how many alarms per operator is acceptable, whether their alarm system is compliant, why operators are ignoring alarms, or wants to know where to start with alarm rationalisation. Trigger even if they don't name a standard - "our operators are drowning in alarms" is this skill.
---

# Alarm Performance Analyser

Measure an alarm system against the benchmarks the standards actually publish, and hand back a report a control room manager can act on.

## Why this exists

Almost every unrationalised alarm system is bad in the same handful of ways: a few tags generate most of the load, instrument noise causes chattering, upsets produce floods no human can process, standing alarms never clear, and priority has been inflated until it carries no information. These are measurable. They do not require an opinion.

What *does* require judgement is deciding what to do about any individual alarm - and that boundary matters enormously. Getting it wrong is how people end up suppressing an alarm that mattered. Keep the two separate: this skill measures, humans decide.

## Workflow

**1. Get the export.** Ask for an alarm & event history covering **at least 30 days** - ISA-18.2 is explicit that shorter windows don't support conclusions about system performance. Useful columns: timestamp, tag, description, priority, event type (alarm/return/ack), and console or operating position. Only timestamp and tag are strictly required.

**2. Establish the operating position count.** This is the single most consequential input, because every rate metric is *per operator position*. An export covering four consoles analysed as one will understate operator load by 4×. If the export has a console column the script auto-detects it; otherwise ask, and pass `--console-count N`. If the user doesn't know, say what you assumed in the summary rather than burying it.

**3. Run the analyser.**

```bash
python scripts/analyse_alarms.py <export.csv> \
    -o assessment.html \
    --site "Plant or console name" \
    --console-count 2 \
    --json metrics.json
```

It is standard-library only, so it runs on locked-down plant networks where `pip install` isn't available 

If column detection fails the script stops and prints what it found. Don't work around this by renaming things at random; ask the user which column is which. A wrong mapping produces a confident, wrong report, which is worse than no report.

**4. Read the report before summarising it.** Open `metrics.json` and lead with what's genuinely notable rather than reciting every metric. A system at 600 alarms/day/operator with 20% of time in flood has one story; a system at 160/day with twelve chattering tags has a completely different one.

**5. Frame the findings as a work queue.** The useful output is not "your alarm system is bad." It's "these eleven tags are 60% of your load, and here is where to start." High concentration is *good* news - it means a bounded remediation list addresses most of the burden.

## The benchmarks

Full detail with sources in `references/benchmarks.md`. The headline figures:

| Metric | Target | Maximum |
|---|---|---|
| Alarms/day/operating position | ~150 | ~300 |
| Alarms/hour | ~6 | ~12 |
| Alarms per 10 min | ~1 | ~2 |
| 10-min periods containing >10 alarms | <1% | — |
| Chattering & fleeting alarms | 0 | — |
| Stale alarms (active >24 h) | <5 on any day | — |
| Priority distribution (low/med/high) | ~80 / 15 / 5 | — |
| Assessment window | ≥30 days | — |

Quote these as what the standards publish, not as your own thresholds. 

## Demonstrating without client data

`scripts/make_demo_data.py` generates a synthetic export with the usual pathologies baked in — useful for teaching, screenshots and testing:

```bash
python scripts/make_demo_data.py -o demo_alarms.csv --days 45
python scripts/analyse_alarms.py demo_alarms.csv -o demo_report.html --site "Site Name Here"
```

Everything it produces is invented. Never present its output as a real site assessment, and say so plainly whenever you share it.

## Where this stops

State this in the report and in conversation - it protects the user and it's simply true.

This tool **measures performance against published benchmarks**. It is not a rationalisation and it is not a compliance record.

Deciding whether a specific alarm should be removed, re-ranged, re-prioritised, suppressed or made state-based requires the P&IDs, the HAZOP and LOPA studies, the defined operator action and consequence for each alarm, and the people who actually run the plant. Those decisions carry safety consequence, need a competent person accountable for them, and under ISA-18.2 and IEC 61511 the rationalisation record must be documented, reviewed and retained.

If someone asks this skill to decide which alarms to delete or suppress, don't. Explain what the decision actually requires and hand back the prioritised queue instead. An alarm that looks like noise in an export can be the last line of protection on a scenario the export doesn't show you.

## Handling sensitive exports

Alarm histories are operational data and frequently confidential. Work on them locally, don't upload them anywhere and if the user wants to share results publicly, point out that tag names alone can identify a site and its process. The report is designed to be readable after tag redaction.
