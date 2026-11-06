#!/usr/bin/env python3
"""
Evaluation Set 2 - parse the in-engine TRIALDATA log into gameplay metrics.

The Unreal trial manager prints one line per gameplay event, prefixed with
"TRIALDATA|". The lines come from actual runtime events (condition evaluated true,
action started, action finished, damage applied, player died) - never from the
behaviour specification. This script only ever aggregates what the engine emitted.

Log line format (pipe separated key=value, order irrelevant):
  TRIALDATA|trial=3|origin=live_pie|behavior=range_based_02|node=n3|event=TRIGGER|t=12.345
  TRIALDATA|trial=3|...|node=n4|event=ACTION_START|action=attack|t=12.401|evt=T03-n3-E001
  TRIALDATA|trial=3|...|node=n4|event=ACTION_RESULT|action=attack|result=SUCCESS|t=12.402|evt=...
  TRIALDATA|trial=3|...|event=DAMAGE|amount=5|t=12.6
  TRIALDATA|trial=3|...|event=TRIAL_END|reason=player_died|survival=8.42|damage_total=45

Metrics produced
  behavior correctness = correct reactions / tested events
  reaction time        = ACTION_START.t - TRIGGER.t, paired on evt id
  failure rate         = failed events / tested events (no ACTION_START within
                         timeout, or ACTION_RESULT != SUCCESS)
  damage dealt         per trial
  player survival time per trial

Usage
  python scripts/analyze_results.py --log "Saved/Logs/Cosmic_Animossity.log"
  python scripts/analyze_results.py --log <file> --out results
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from collections import defaultdict

PREFIX = "TRIALDATA|"
FIELDS = ("trial", "origin", "behavior", "node", "event", "action", "result",
          "evt", "t", "amount", "reason", "survival", "damage_total", "player_dist")


def parse_line(line):
    idx = line.find(PREFIX)
    if idx < 0:
        return None
    record = {}
    for part in line[idx + len(PREFIX):].strip().split("|"):
        if "=" in part:
            key, value = part.split("=", 1)
            record[key.strip()] = value.strip()
    return record if record.get("event") else None


def read_records(path):
    records = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            record = parse_line(line)
            if record:
                records.append(record)
    return records


def fnum(record, key, default=0.0):
    try:
        return float(record.get(key, default))
    except (TypeError, ValueError):
        return default


def analyze(records, reaction_timeout):
    trials = defaultdict(lambda: {"events": [], "damage": 0.0, "survival": None, "reason": "",
                                 "origin": "", "behavior": ""})
    for record in records:
        trial = record.get("trial", "0")
        bucket = trials[trial]
        bucket["events"].append(record)
        bucket["origin"] = record.get("origin", bucket["origin"])
        bucket["behavior"] = record.get("behavior", bucket["behavior"])
        event = record.get("event")
        if event == "DAMAGE":
            bucket["damage"] += fnum(record, "amount")
        elif event == "TRIAL_END":
            bucket["survival"] = fnum(record, "survival", None)
            bucket["reason"] = record.get("reason", "")
            if record.get("damage_total"):
                bucket["damage"] = fnum(record, "damage_total", bucket["damage"])

    rows, event_rows = [], []
    for trial in sorted(trials, key=lambda x: (len(x), x)):
        bucket = trials[trial]
        triggers = [r for r in bucket["events"] if r.get("event") == "TRIGGER"]
        starts = {r.get("evt"): r for r in bucket["events"] if r.get("event") == "ACTION_START"}
        results = {r.get("evt"): r for r in bucket["events"] if r.get("event") == "ACTION_RESULT"}

        tested = correct = failed = 0
        reactions = []
        for trigger in triggers:
            evt = trigger.get("evt", "")
            expected = trigger.get("expected", "")
            # pairing is by unique event id; a missing counterpart is a real failure,
            # never filled in from the specification
            start = starts.get(evt)
            result = results.get(evt)
            action = (start or result or {}).get("action", "")
            reaction = None
            if start:
                reaction = fnum(start, "t") - fnum(trigger, "t")
                reactions.append(reaction)
            success = bool(result) and result.get("result", "").upper() == "SUCCESS"
            timed_out = start is None and reaction_timeout > 0 and reaction is None
            is_correct = bool(expected) and action == expected and success
            tested += 1
            if is_correct:
                correct += 1
            if not start or not success or timed_out:
                failed += 1
            event_rows.append({
                "trial": trial, "origin": bucket["origin"], "behavior": bucket["behavior"],
                "evt": evt, "node": trigger.get("node", ""), "expected_action": expected,
                "actual_action": action, "correct": int(is_correct),
                "reaction_s": "" if reaction is None else round(reaction, 4),
                "action_started": int(bool(start)),
                "action_success": int(success),
                "failure_reason": ("no_action" if not start else
                                   ("action_failed" if not success else "")),
                "trigger_t": round(fnum(trigger, "t"), 4),
            })

        rows.append({
            "trial": trial,
            "origin": bucket["origin"],
            "behavior": bucket["behavior"],
            "tested_events": tested,
            "correct_events": correct,
            "failed_events": failed,
            "correctness_pct": "" if not tested else round(100.0 * correct / tested, 2),
            "failure_rate_pct": "" if not tested else round(100.0 * failed / tested, 2),
            "mean_reaction_s": "" if not reactions else round(sum(reactions) / len(reactions), 4),
            "min_reaction_s": "" if not reactions else round(min(reactions), 4),
            "max_reaction_s": "" if not reactions else round(max(reactions), 4),
            "damage_dealt": round(bucket["damage"], 2),
            "player_survival_s": "" if bucket["survival"] is None else round(bucket["survival"], 3),
            "end_reason": bucket["reason"],
        })
    return rows, event_rows


def write_csv(rows, path, fields):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summarize(rows):
    live = [r for r in rows if r["origin"] == "live_pie"]
    fixture = [r for r in rows if r["origin"] != "live_pie"]
    lines = []
    for label, group in (("live PIE trials", live), ("fixture/dry-run trials (not experimental data)", fixture)):
        if not group:
            continue
        tested = sum(int(r["tested_events"]) for r in group)
        correct = sum(int(r["correct_events"]) for r in group)
        failed = sum(int(r["failed_events"]) for r in group)
        reactions = [float(r["mean_reaction_s"]) for r in group if r["mean_reaction_s"] != ""]
        lines.append("%s: N=%d trials, events=%d, correctness=%.1f%%, failure=%.1f%%, mean reaction=%.3fs, "
                     "damage=%.1f, survival=%.2fs"
                     % (label, len(group), tested,
                        0.0 if not tested else 100.0 * correct / tested,
                        0.0 if not tested else 100.0 * failed / tested,
                        sum(reactions) / len(reactions) if reactions else 0.0,
                        sum(float(r["damage_dealt"]) for r in group),
                        sum(float(r["player_survival_s"] or 0) for r in group)))
    return "\n".join(lines) if lines else "No TRIALDATA records found."


def main(argv=None):
    parser = argparse.ArgumentParser(description="Parse TRIALDATA gameplay logs into CSV.")
    parser.add_argument("--log", default=None, help="log file; defaults to newest Saved/Logs/*.log")
    parser.add_argument("--out", default="results")
    parser.add_argument("--reaction-timeout", type=float, default=2.0,
                        help="seconds after which a trigger with no action counts as failed")
    args = parser.parse_args(argv)

    log_path = args.log
    if not log_path:
        candidates = sorted(glob.glob(os.path.join("Saved", "Logs", "*.log")), key=os.path.getmtime)
        if not candidates:
            sys.exit("ERROR: no log found in Saved/Logs and --log was not given.")
        log_path = candidates[-1]

    records = read_records(log_path)
    if not records:
        sys.exit("ERROR: %s contains no TRIALDATA lines." % log_path)

    rows, event_rows = analyze(records, args.reaction_timeout)
    trials_csv = os.path.join(args.out, "gameplay_trials.csv")
    events_csv = os.path.join(args.out, "gameplay_events.csv")
    write_csv(rows, trials_csv, ["trial", "origin", "behavior", "tested_events", "correct_events",
                                 "failed_events", "correctness_pct", "failure_rate_pct",
                                 "mean_reaction_s", "min_reaction_s", "max_reaction_s",
                                 "damage_dealt", "player_survival_s", "end_reason"])
    write_csv(event_rows, events_csv, ["trial", "origin", "behavior", "evt", "node", "expected_action",
                                       "actual_action", "correct", "reaction_s", "action_started",
                                       "action_success", "failure_reason", "trigger_t"])
    print("log: %s (%d TRIALDATA records)" % (log_path, len(records)))
    print(summarize(rows))
    print("CSV: %s" % trials_csv)
    print("CSV: %s" % events_csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
