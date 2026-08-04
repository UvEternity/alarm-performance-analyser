#!/usr/bin/env python3
"""
Synthetic alarm & event export generator
========================================
Produces a realistic-looking alarm export for demonstrating the analyser without
using any real plant data. Everything here is invented: tag names follow generic
ISA-5.1 conventions, and the pathologies injected (bad actors, chattering,
floods, stale alarms, priority inflation) are the ones almost every unrationalised
system exhibits.

Use this for demos, screenshots, teaching and testing. Never present output from
this generator as a real site assessment.

Usage:
    python make_demo_data.py [-o demo_alarms.csv] [--days 45] [--seed 7]
"""

import argparse
import csv
import random
from datetime import datetime, timedelta

AREAS = ["MILL", "FLOT", "THKN", "FILT", "REAG", "UTIL"]
CONSOLES = {"MILL": "Console 1", "FLOT": "Console 1", "THKN": "Console 2",
            "FILT": "Console 2", "REAG": "Console 2", "UTIL": "Console 1"}

MEASUREMENTS = [
    ("PT", "pressure", ["HI", "HIHI", "LO"]),
    ("TT", "temperature", ["HI", "HIHI", "LO"]),
    ("FT", "flow", ["LO", "LOLO", "HI"]),
    ("LT", "level", ["HI", "HIHI", "LO", "LOLO"]),
    ("DT", "density", ["HI", "LO"]),
    ("VT", "vibration", ["HI", "HIHI"]),
    ("AT", "analyser", ["HI", "LO"]),
    ("ZT", "position", ["DEV"]),
    ("XA", "motor", ["FAULT", "TRIP"]),
    ("PDT", "diff pressure", ["HI", "LO"]),
]

EQUIP = ["Ball mill 01", "Ball mill 02", "Cyclone cluster A", "Cyclone cluster B",
         "Rougher cell 1", "Rougher cell 2", "Cleaner cell 1", "Scavenger cell 3",
         "Thickener 1 underflow", "Thickener 2 rake", "Filter press 1",
         "Filter press 2", "Reagent dosing pump A", "Reagent dosing pump B",
         "Process water tank", "Instrument air receiver", "Sump pump 4",
         "Conveyor CV-201", "Conveyor CV-202", "Slurry pump SP-11",
         "Slurry pump SP-12", "Cooling water header", "Flocculant mixer",
         "Lime silo", "Tailings line", "Gland water header"]

SUFFIX_TEXT = {"HI": "high", "HIHI": "high high", "LO": "low", "LOLO": "low low",
               "DEV": "deviation", "FAULT": "fault", "TRIP": "trip"}


def build_tag_catalogue(rng, n=340):
    tags = []
    for i in range(n):
        prefix, kind, suffixes = rng.choice(MEASUREMENTS)
        area = rng.choice(AREAS)
        num = rng.randint(100, 999)
        suffix = rng.choice(suffixes)
        tag = "{}-{}{:03d}_{}".format(area, prefix, num, suffix)
        equip = rng.choice(EQUIP)
        desc = "{} {} {}".format(equip, kind, SUFFIX_TEXT[suffix])
        # priority inflation: most unrationalised systems over-assign High
        roll = rng.random()
        if suffix in ("HIHI", "LOLO", "TRIP"):
            pri = "High"
        elif roll < 0.34:
            pri = "High"
        elif roll < 0.62:
            pri = "Medium"
        else:
            pri = "Low"
        tags.append({"tag": tag, "desc": desc, "priority": pri,
                     "console": CONSOLES[area], "area": area})
    return tags


def main():
    p = argparse.ArgumentParser(description="Generate a synthetic alarm & event export.")
    p.add_argument("-o", "--output", default="demo_alarms.csv")
    p.add_argument("--days", type=int, default=45)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()

    rng = random.Random(args.seed)
    catalogue = build_tag_catalogue(rng)
    start = datetime(2026, 6, 1, 0, 0, 0)
    end = start + timedelta(days=args.days)
    events = []

    def emit(ts, t, state):
        events.append({
            "Timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "Tag": t["tag"],
            "Description": t["desc"],
            "Priority": t["priority"],
            "EventType": state,
            "Console": t["console"],
        })

    def alarm_cycle(ts, t, duration_s=None):
        emit(ts, t, "ALM")
        dur = duration_s if duration_s is not None else rng.randint(20, 5400)
        emit(ts + timedelta(seconds=dur), t, "RTN")

    # --- 1. Background load: steady, unremarkable ---------------------------
    background = catalogue[40:]
    t = start
    while t < end:
        # diurnal shape - busier on day shift, spikes at shift change
        hour = t.hour
        base = 0.55
        if 6 <= hour < 18:
            base = 1.0
        if hour in (6, 14, 22):
            base = 1.9
        gap = rng.expovariate(base / 240.0)
        t += timedelta(seconds=max(gap, 5))
        if t >= end:
            break
        alarm_cycle(t, rng.choice(background))

    # --- 2. Bad actors: a handful of tags generating most of the load -------
    bad_actors = catalogue[:8]
    for idx, tag in enumerate(bad_actors):
        rate_per_day = [190, 150, 120, 95, 78, 61, 47, 38][idx]
        n = int(rate_per_day * args.days * rng.uniform(0.85, 1.15))
        for _ in range(n):
            ts = start + timedelta(seconds=rng.uniform(0, args.days * 86400))
            alarm_cycle(ts, tag, rng.randint(15, 900))

    # --- 3. Chattering: instrument noise on a few loops ---------------------
    chatterers = catalogue[8:14]
    for tag in chatterers:
        bursts = rng.randint(24, 70)
        for _ in range(bursts):
            burst_start = start + timedelta(seconds=rng.uniform(0, args.days * 86400))
            for k in range(rng.randint(4, 13)):
                ts = burst_start + timedelta(seconds=k * rng.uniform(3, 11))
                alarm_cycle(ts, tag, rng.randint(2, 8))

    # --- 4. Flood episodes: trips and upsets --------------------------------
    for _ in range(rng.randint(9, 15)):
        onset = start + timedelta(seconds=rng.uniform(0, args.days * 86400))
        size = rng.randint(45, 210)
        involved = rng.sample(catalogue, min(size, len(catalogue)))
        for i, tag in enumerate(involved):
            ts = onset + timedelta(seconds=rng.expovariate(1 / 130.0) + i * 0.6)
            alarm_cycle(ts, tag, rng.randint(60, 2400))

    # --- 5. Stale alarms: standing conditions nobody clears -----------------
    for tag in catalogue[14:26]:
        onset = start + timedelta(seconds=rng.uniform(0, args.days * 0.6 * 86400))
        hours = rng.uniform(26, 400)
        emit(onset, tag, "ALM")
        if rng.random() < 0.6:
            emit(onset + timedelta(hours=hours), tag, "RTN")
        # else: left active to end of window

    events.sort(key=lambda e: e["Timestamp"])

    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["Timestamp", "Tag", "Description",
                                           "Priority", "EventType", "Console"])
        w.writeheader()
        w.writerows(events)

    activations = sum(1 for e in events if e["EventType"] == "ALM")
    print("Wrote {:,} event rows ({:,} activations) across {} days to {}".format(
        len(events), activations, args.days, args.output))
    print("Synthetic data only - not from any real plant.")


if __name__ == "__main__":
    main()
