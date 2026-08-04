# Alarm Performance Analyser

A free, open tool that benchmarks industrial alarm & event exports against the
published performance targets in ANSI/ISA-18.2 and EEMUA 191, and produces a
self-contained HTML assessment report.

Author: Uveer Maharaj. Licence: MIT. Repo: alarm-performance-analyser (public).

## What matters in this codebase

**Dependency-free is a requirement, not a preference.** `scripts/analyse_alarms.py`
uses the Python standard library only. The target users are engineers on locked-down
plant networks where `pip install` is not available and internet access is blocked.
Do not add pandas, numpy, matplotlib, jinja2 or any other dependency. Charts are
hand-rolled inline SVG for exactly this reason.

**Benchmark values are quotations, not settings.** Every threshold in the `BENCH`
dict comes from a published standard and is cited in `references/benchmarks.md`.
If you change a value, update the reference doc and the source in the same commit.
The credibility of the whole tool rests on a user being able to check any number
against their own copy of the standard.

The one exception is the chattering criterion (3+ activations within a rolling 60s).
The standards define chattering qualitatively without a numeric rule, so this is an
operationalisation. It is documented as such — keep it that way rather than presenting
it as a quotation.

**The measure/decide boundary is deliberate and load-bearing.** This tool measures
alarm system performance. It must never recommend which alarms to delete, suppress,
re-range or re-prioritise. Those decisions need the P&IDs, the HAZOP and LOPA record,
the defined operator action per alarm, and a competent person accountable for the
outcome. An alarm that looks like noise in a log can be the last protection layer on
a scenario the log doesn't show. If a feature request crosses that line, push back.

**Column detection fails loudly on purpose.** If timestamp and tag columns can't be
identified, the script exits with what it found rather than guessing. A wrong mapping
produces a confident, wrong report, which is worse than an error. Don't add fallback
guessing.

**Rates are per operating position.** Every rate metric divides by console count.
This is the most commonly botched part of an alarm assessment — a six-console export
analysed as one understates operator load six-fold.

## Data handling

Never commit alarm data. `.gitignore` blocks `*.csv`, `*.tsv` and Excel formats.
Tag names alone can identify a site and its process. All sample data must come from
`scripts/make_demo_data.py`, which is synthetic. Never use real plant data from any
employer or client, in any form, anywhere in this repo.

## Layout

    SKILL.md                 Claude skill definition (triggering + workflow)
    README.md                public landing page
    scripts/analyse_alarms.py    the engine
    scripts/make_demo_data.py    synthetic export generator
    references/benchmarks.md     every threshold, its source, and known limitations
    examples/demo_report.html    sample output from synthetic data

## Verifying a change

    python scripts/make_demo_data.py -o /tmp/d.csv --days 45 --seed 7
    python scripts/analyse_alarms.py /tmp/d.csv -o /tmp/d.html --site "Test"

With seed 7 over 45 days this is deterministic and should give ~611 alarms/day/position,
22.3% time in flood, 14 chattering tags and 11 stale alarms. If those move, you changed
a metric definition — intended or not, say which in the commit message.