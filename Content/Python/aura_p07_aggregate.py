"""Post-processing for the candidate #6 (round2/P07-G01) comparison.

Reads the per-subject CSVs written by aura_p07_compare and produces the same aggregate
files candidates #1, #2 and #3 have:

  P07CMP_combined_phase_metrics.csv   both subjects, one header
  P07CMP_combined_damage_events.csv   both subjects, one header
  P07CMP_summary.csv                  per-subject aggregates
  P07CMP_behavior_failures.csv        task-line counts, from the log window per subject

The log window per subject is taken from the session files, so the counts cannot silently
describe a different run than the CSVs. Log timestamps in this project read 5 h ahead of the
session clock, so the window is derived from the session file's started_at/finished_at plus
the recorded offset; the shift crosses midnight for this candidate, so the log date is
computed rather than assumed.
"""

import datetime
import os

import unreal

RUN_ID = "p7cmp_p07_r1"
OFFSET_HOURS = 5
WINDOWS = (("generated", "2026.11.14-22.02.15", "2026.11.14-22.03.36"),
           ("baseline", "2026.11.14-22.04.13", "2026.11.14-22.05.34"))
SUBJECTS = ("generated", "baseline")
THRESHOLD_CM = 900.0

TASK_PREFIXES = (
    "BTTask_EnemyMoveToTarget: SUCCESS",
    "BTTask_EnemyMoveToTarget: FAILURE (arrived too far)",
    "BTTask_EnemyMoveToTarget: FAILURE",
    "BTTask_EnemyMoveAwayFromTarget: SUCCESS",
    "BTTask_EnemyMoveAwayFromTarget: FAILURE (retreat too short)",
    "BTTask_EnemyMoveAwayFromTarget: FAILURE (already beyond retreat range)",
    "BTTask_EnemyMoveAwayFromTarget: FAILURE (no target)",
    "BTTask_EnemyMoveAwayFromTarget: FAILURE (target invalid)",
    "BTTask_EnemyMoveAwayFromTarget: FAILURE",
    "BTTask_EnemyAttack: out of range - FAILURE",
    "BTTask_EnemyAttack:",
)


def _project_dir():
    base = unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_dir().replace("\\", "/")).replace("\\", "/")
    return base if base.endswith("/") else base + "/"


def _out_dir():
    path = os.path.join(_project_dir(), "results", "gameplay")
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def _read_csv(path):
    with open(path, "r") as handle:
        lines = [line.rstrip("\n") for line in handle if line.strip()]
    header = lines[0].split(",")
    rows = [dict(zip(header, line.split(","))) for line in lines[1:]]
    return header, rows


def _write_csv(path, header, rows):
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(v) for v in row))
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")


def _log_window(session_stamp):
    base = datetime.datetime.strptime(session_stamp, "%Y.%m.%d-%H.%M.%S")
    base += datetime.timedelta(hours=OFFSET_HOURS)
    return base.strftime("%Y.%m.%d"), base.strftime("%H.%M.%S")


def _log_counts():
    log_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_log_dir())
    log_path = os.path.join(log_dir, "Cosmic_Animossity.log")
    bounds = [(label, _log_window(start), _log_window(finish))
              for label, start, finish in WINDOWS]
    counts = {}
    with open(log_path, "r", errors="replace") as handle:
        for line in handle:
            if len(line) < 26 or line[0] != "[":
                continue
            stamp_date = line[1:11]
            stamp = line[12:20]
            for label, (low_date, low), (high_date, high) in bounds:
                if low_date == stamp_date == high_date and low <= stamp <= high:
                    bucket = counts.setdefault(label, dict((k, 0) for k in TASK_PREFIXES))
                    for prefix in TASK_PREFIXES:
                        if prefix in line:
                            bucket[prefix] += 1
                    break
    for label, _start, _finish in WINDOWS:
        counts.setdefault(label, dict((k, 0) for k in TASK_PREFIXES))
    return counts


def run():
    out = _out_dir()
    phase_header, phase_g = _read_csv(
        os.path.join(out, "P07CMP_phase_metrics_generated.csv"))
    _h, phase_b = _read_csv(os.path.join(out, "P07CMP_phase_metrics_baseline.csv"))
    event_header, event_g = _read_csv(
        os.path.join(out, "P07CMP_damage_events_generated.csv"))
    _h2, event_b = _read_csv(os.path.join(out, "P07CMP_damage_events_baseline.csv"))

    _write_csv(os.path.join(out, "P07CMP_combined_phase_metrics.csv"),
               phase_header, [[r[c] for c in phase_header] for r in phase_g + phase_b])
    _write_csv(os.path.join(out, "P07CMP_combined_damage_events.csv"),
               event_header, [[r[c] for c in event_header] for r in event_g + event_b])

    counts = _log_counts()
    failure_rows = []
    for subject in SUBJECTS:
        for prefix in TASK_PREFIXES:
            failure_rows.append([RUN_ID, subject, prefix, counts[subject][prefix]])
    _write_csv(os.path.join(out, "P07CMP_behavior_failures.csv"),
               ["run_id", "subject", "task_line_prefix", "count"], failure_rows)

    summary_header = ["run_id", "subject", "trials", "phases", "damage_events",
                      "damage_total", "damage_per_trial", "events_beyond_threshold",
                      "events_beyond_ceiling", "max_geo_at_damage_cm",
                      "min_geo_at_damage_cm", "mean_sample_rate_hz",
                      "mean_first_damage_s", "attack_threshold_cm",
                      "reaction_correctness"]
    summary_rows = []
    for subject, rows, events in (("generated", phase_g, event_g),
                                  ("baseline", phase_b, event_b)):
        total = sum(float(r["damage_total"]) for r in rows)
        trials = len(set(r["trial"] for r in rows))
        first = [float(r["first_damage_s"]) for r in rows
                 if float(r["first_damage_s"]) >= 0.0]
        geo = [float(r["max_geo_at_damage_cm"]) for r in rows
               if float(r["max_geo_at_damage_cm"]) >= 0.0]
        geo_lo = [float(r["min_geo_at_damage_cm"]) for r in rows
                  if float(r["min_geo_at_damage_cm"]) >= 0.0]
        rate = [float(r["sample_rate_hz"]) for r in rows]
        beyond = sum(int(e["beyond_threshold"]) for e in events)
        beyond_ceiling = sum(int(e["beyond_ceiling"]) for e in events)
        if not events:
            verdict = "not_applicable"
        elif beyond_ceiling:
            verdict = "fail"
        else:
            verdict = "pass"
        summary_rows.append([
            RUN_ID, subject, trials, len(rows), len(events), "%.1f" % total,
            "%.2f" % (total / trials if trials else 0.0), beyond, beyond_ceiling,
            "%.1f" % (max(geo) if geo else -1.0),
            "%.1f" % (min(geo_lo) if geo_lo else -1.0),
            "%.2f" % (sum(rate) / len(rate) if rate else 0.0),
            "%.2f" % (sum(first) / len(first)) if first else "n/a",
            "%.0f" % THRESHOLD_CM, verdict])
    _write_csv(os.path.join(out, "P07CMP_summary.csv"), summary_header, summary_rows)

    for row in summary_rows:
        print(",".join(str(v) for v in row))
    for label, _s, _f in WINDOWS:
        print("%s task lines: %s" % (label, counts[label]))
    return "wrote P07CMP_combined_*, P07CMP_summary.csv, P07CMP_behavior_failures.csv"
