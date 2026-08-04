# Alarm performance benchmarks — figures and sources

Every threshold this tool scores against comes from a published standard or guideline. Nothing here is a house rule. If a client challenges a number, they should be able to check it against their own copy of the standard — that is the point.

## Contents

- [The two documents](#the-two-documents)
- [Rate metrics](#rate-metrics)
- [Flood metrics](#flood-metrics)
- [Chattering, fleeting and stale](#chattering-fleeting-and-stale)
- [Priority distribution](#priority-distribution)
- [Bad actor concentration](#bad-actor-concentration)
- [Assessment window](#assessment-window)
- [How this tool computes each metric](#how-this-tool-computes-each-metric)
- [What the numbers do not tell you](#what-the-numbers-do-not-tell-you)

---

## The two documents

**ANSI/ISA-18.2** — *Management of Alarm Systems for the Process Industries*. The North American standard, first issued 2009, current edition 2016. Internationally adopted as **IEC 62682**. It defines the alarm management lifecycle and publishes target performance metrics.

**EEMUA Publication 191** — *Alarm Systems: A Guide to Design, Management and Procurement*. First published 1999, revised 2007, 2013, and a **4th edition in November 2024**. The globally accepted good-practice reference, widely cited in UK/EU and Commonwealth operations.

The two agree closely on performance targets. Where this tool cites a figure, both support it unless noted.

---

## Rate metrics

Rates are always expressed **per operating position** (per operator console), not per plant. This is the most commonly botched part of an alarm assessment: a site with six consoles reporting a plant-wide figure will look six times better than operators actually experience.

| Metric | Target | Maximum manageable |
|---|---|---|
| Annunciated alarms per day per operating position | ~150 | ~300 |
| Annunciated alarms per hour per operating position | ~6 | ~12 |
| Annunciated alarms per 10 minutes per operating position | ~1 | ~2 |

EEMUA 191 frames the acceptable figure as **no more than one alarm per operator per ten minutes during normal operation**, which is the same ~150/day. ISA-18.2 presents the pair of values as "very likely acceptable" (150) and "maximum manageable" (300).

The 300/day figure is frequently misquoted as a target. It is not — it is the point beyond which an operator is definitely overloaded. Design to 150.

---

## Flood metrics

An **alarm flood** is conventionally defined as a period in which alarms arrive faster than an operator can reasonably process them.

| Metric | Threshold |
|---|---|
| Flood condition | **more than 10 alarms in a 10-minute window** per operating position |
| Percentage of 10-minute periods in flood | target **<1%** |

EEMUA 191 (4th edition, November 2024) expresses the related design expectation that during a major plant upset **no more than ten alarms should present in the first ten minutes**.

Floods matter disproportionately because they cluster around exactly the moments operators most need the alarm system to work. Alarm floods are repeatedly identified in incident literature as a contributing factor to serious upsets and major accidents — the operator was not short of information, they were buried in it.

---

## Chattering, fleeting and stale

**Chattering alarm** — an alarm that repeatedly transitions between alarm and normal state in a short period. Usually instrument noise around a setpoint, a missing deadband, or a genuinely unstable process.

**Fleeting alarm** — an alarm that activates and clears so quickly the operator cannot act on it.

**Stale alarm** — an alarm that remains in the alarm state for an extended period, conventionally **more than 24 hours**.

| Metric | Target |
|---|---|
| Quantity of chattering and fleeting alarms | **0** |
| Stale alarms (active >24 h) | **fewer than 5 on any day** |

Chattering is worth attacking first in almost every assessment: it is high-volume, low-value, and usually fixable with deadband or filtering rather than a rationalisation workshop. Stale alarms are more insidious — a permanently lit annunciator teaches operators that the alarm system is background noise.

**This tool's chattering criterion:** 3 or more activations of the same tag within any rolling 60-second window. The standards define chattering qualitatively rather than giving a numeric rule, so this is an operationalisation, not a quotation. It is deliberately conservative — it will catch genuine chatter without flagging an alarm that simply cycled twice. Adjust `chatter_per_min` in the script if a site has a house definition, and say which you used.

---

## Priority distribution

ISA-18.2 gives a recommended distribution of annunciated alarm priorities:

| Priority | Share |
|---|---|
| Low | ~80% |
| Medium | ~15% |
| High | ~5% |

Some sites operate a four-tier scheme with an additional emergency/critical band, typically ~80 / 15 / 5 / <1.

Priority inflation is the most common single finding in an unrationalised system. It happens gradually and for understandable reasons — every engineer commissioning a loop believes their alarm is important. The consequence is that during an upset the operator cannot distinguish the alarm that matters from forty that don't.

---

## Bad actor concentration

Not a formal standard metric, but universally used in practice: the **top 10 contributing tags** should account for only a small share of total alarm load. This tool flags concentration above **~5%** as worth attention.

Interpretation matters here and is frequently got backwards. High concentration is **good news for the remediation plan** — if ten tags are producing 60% of the load, a short, bounded piece of work removes most of the burden. Low concentration with a high overall rate is the harder problem, because it means the load is spread across hundreds of tags and there is no shortcut.

---

## Assessment window

ISA-18.2 recommends alarm performance be assessed on **at least 30 days** of data.

Shorter windows are legitimate for a quick look but should be labelled as indicative. A single week can be dominated by one upset, or can miss a monthly batch or regeneration cycle entirely. This tool prints a warning on the report whenever the window is under 30 days.

---

## How this tool computes each metric

Transparency here is deliberate — anyone should be able to reproduce these numbers independently, and several of the definitions involve choices that a different practitioner might make differently.

| Metric | Method |
|---|---|
| Activations | Rows classified as an alarm transition. Return-to-normal and acknowledge rows are excluded from rate counts. |
| Span | First to last activation timestamp. |
| Per day / per hour | Total activations ÷ span ÷ operating position count. |
| 10-minute windows | Wall-clock aligned buckets of 600 s across the full span, including empty windows. Excluding empty windows would flatter the flood percentage. |
| Flood window | Any 10-minute bucket with >10 activations. |
| Flood episode | Contiguous run of flood windows, reported with duration, total alarms and peak. |
| Chattering | Rolling 60-second window per tag; flagged at ≥3 activations. See caveat above. |
| Stale | Alarm-to-return duration ≥24 h. Alarms still active at the end of the window are measured to the window end and marked "still active". |
| Priority | Normalised to high/medium/low/unassigned. Numeric schemes map 1→high, 2→medium, 3+→low. Text schemes match on substring. |
| Bad actors | Activation count per tag, ranked. |

**Known limitations, stated plainly:**

- If the export lacks an event-type column, every row is treated as an activation. That inflates rates for exports that include returns. The script reports its column mapping so this is visible.
- Suppressed and shelved alarms are counted as activations if they appear in the export. Some historians exclude them; some don't. Worth checking with the site before quoting a figure.
- Priority normalisation is best-effort across vendor schemes. Verify the mapping against the site's own convention before presenting results.
- Operating position count defaults to the number of distinct console values, or 1 if absent. Getting this wrong scales every rate metric proportionally — always confirm it.

---

## What the numbers do not tell you

A system can meet every metric here and still be unsafe, and a system can fail several and be operationally tolerable. The metrics measure *load*, not *correctness*.

None of these figures tell you whether each alarm has a defined operator action, whether the setpoint gives enough time to respond before the consequence occurs, whether the alarm is credited as a protection layer in a LOPA study, or whether the priority reflects actual consequence severity. Those questions are what rationalisation answers, and they require the P&IDs, the hazard study record, and the people who run the plant.

Use this assessment to find where to look. Not to decide what to do.

---

## Sources

- [ANSI/ISA-18.2 — Understanding and Applying the Alarm Management Standard (ISA/PAS)](https://www.isa.org/getmedia/55b4210e-6cb2-4de4-89f8-2b5b6b46d954/PAS-Understanding-ISA-18-2.pdf)
- [Alarm System Performance Metrics — ISA Ireland](https://isa.ie/wp-content/uploads/2016/06/Alarm_System_Performance_Metrics_Kim_Van_camp.pdf)
- [EEMUA Publication 191 — Alarm Systems: A Guide to Design, Management and Procurement](https://www.eemua.org/products/publications/digital/eemua-publication-191)
- [ISA-18.2 Alarm Management Standards and Guidelines — ProcessVue](https://www.processvue.com/resources/alarm-management-guidelines/)
- [The Sense and Nonsense of Alarm System Performance KPIs — ProcessVue](https://www.processvue.com/downloads/Alarm_system_performance_KPIs_V1_0.pdf)
- [Alarm Management Standards and Best Practices — Empowered Automation](https://www.empoweredautomation.com/alarm-management-standards-and-best-practices)
- [Alarm Management — exida standards and guidelines](https://www.exida.com/Alarm-Management/Detail/standards_guidelines)
- [Lead Process Safety Metrics: Alarm Rationalisation — IChemE](https://www.icheme.org/media/17392/lc-0151_21-lead-process-safety-metrics-alarm-rationalisation-final.pdf)
- [Introduction to the ISA 18.2 Alarm Management Standard — Graham Nasby](https://www.grahamnasby.com/files_publications/NasbyG_2013_IntroToAlarmMgmt_YorkRegion_oct2013_slides.pdf)
