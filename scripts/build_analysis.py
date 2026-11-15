#!/usr/bin/env python3
"""Rebuild every consolidated CSV in ``results/analysis/`` from the preserved sources.

Standard library only. Reads (never writes) the preserved measurement files and
writes only into ``results/analysis/``.

Usage (from the project root):

    python scripts/build_analysis.py

Sources, all read-only:

    results/validation_combined.csv
    results/gameplay/<prefix>_phase_metrics_{generated,baseline}.csv
    results/gameplay/<prefix>_summary.csv
    results/gameplay/<prefix>_behavior_failures.csv
    results/gameplay/G1*_phases.csv

with prefix in {P7CMP, P02CMP, P04CMP, P07CMP, P03CMP, P01G2CMP}.

Six of the eight outputs are DERIVED from those files and are byte-reproducible.
Two are ANALYST-CURATED and are defined here as data tables, because they encode
judgements that no source file contains: ``action_reachability.csv`` (what a run
established about each action) and ``failure_attribution.csv`` (which layer
produced each finding). Keeping them in this script means the derivation and the
curated records travel together in version control.

Nothing here re-runs an experiment, re-saves a Behaviour Tree, or touches
``dataset/`` or any pre-existing result file.
"""

import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAMEPLAY = os.path.join(ROOT, "results", "gameplay")
OUT = os.path.join(ROOT, "results", "analysis")

# --- candidate metadata (curated: identity and authored parameters only) -----
# (no, sample_id, tree asset, source prefix, attack_range_cm, nodes, status, finding)
CAND = [
    (1, "P01-G01", "BT_Behavior_P01_G01", "P7CMP", 300, 5, "VALID", "none"),
    (2, "P02-G01", "BT_Behavior_P02_G01", "P02CMP", 800, 7, "VALID", "none"),
    (3, "P04-G01", "BT_Behavior_P04_G01", "P04CMP", 1500, 12, "VALID", "none"),
    (6, "P07-G01", "BT_Behavior_P07_G01", "P07CMP", 900, 7, "VALID", "none"),
    (5, "P03-G02", "BT_Behavior_P03_G02", "P03CMP", 1000, 10, "REVIEW", "L5"),
    (4, "P01-G02", "BT_Behavior_P01_G02", "P01G2CMP", 250, 5, "REVIEW", "L3"),
]

# which round-2 outputs were translated into Unreal assets
SELECTED = {
    "P01-G01": (1, "BT_Behavior_P01_G01", "p7cmp_r1"),
    "P02-G01": (2, "BT_Behavior_P02_G01", "p7cmp_p02_r1"),
    "P04-G01": (3, "BT_Behavior_P04_G01", "p7cmp_p04_r1"),
    "P01-G02": (4, "BT_Behavior_P01_G02", "p7cmp_p01g2_r1"),
    "P03-G02": (5, "BT_Behavior_P03_G02", "p7cmp_p03g2_r1"),
    "P07-G01": (6, "BT_Behavior_P07_G01", "p7cmp_p07_r1"),
}

COMPLIANCE_RULE = "pass iff 0 damage events beyond attack_range_cm + 50 cm"
COMPLIANCE_NOTE = ("harness column is named reaction_correctness, but the rule implemented "
                   "measures distance-at-damage compliance only; it is not a test of broader "
                   "reaction correctness")


def read(path):
    fh = open(path, "r", encoding="utf-8", errors="replace", newline="")
    try:
        return list(csv.DictReader(fh))
    finally:
        fh.close()


def read_gp(name):
    return read(os.path.join(GAMEPLAY, name))


def write(name, header, rows):
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    path = os.path.join(OUT, name)
    fh = open(path, "w", encoding="utf-8", newline="\n")
    try:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    finally:
        fh.close()
    print("wrote %-40s %d rows" % (name, len(rows)))


def fnum(s, default=None):
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def f2(v, nd=2):
    if v is None:
        return "n/a"
    return ("%." + str(nd) + "f") % v


def f1(v):
    return f2(v, 1)


def whole(v):
    x = float(v)
    return str(int(round(x))) if abs(x - round(x)) < 1e-9 else "%.1f" % x


# ---------------------------------------------------------------- Set 1
def build_set1():
    rows = read(os.path.join(ROOT, "results", "validation_combined.csv"))
    out = []
    for r in rows:
        key = (r["run_id"], r["sample_id"])
        cand = SELECTED.get(r["sample_id"]) if r["run_id"] == "20261105_round2" else None
        out.append([
            r["sample_id"], r["run_id"], r["sample_id"].split("-")[0], r["behavior_id"],
            r["schema_version"], r["json_valid"], r["structural_valid"], r["actions_valid"],
            r["logical_status"], r["manual_review"], r["correction_class"], r["finding_codes"],
            "selected_candidate" if cand else "not_selected",
            cand[0] if cand else "",
            cand[1] if cand else "",
            cand[2] if cand else "",
        ])
    out.sort(key=lambda x: (x[1], x[0]))
    write("set1_validation_40.csv",
          ["sample_id", "run_id", "prompt_family", "behavior_id", "schema_version", "json_valid",
           "structural_valid", "actions_valid", "logical_status", "manual_review",
           "correction_class", "finding_codes", "selection", "candidate_no", "tree_asset",
           "gameplay_run_id"], out)

    fam = {}
    for r in rows:
        key = r["sample_id"].split("-")[0]
        d = fam.setdefault(key, {"VALID": 0, "REVIEW": 0, "INVALID": 0})
        d[r["logical_status"]] += 1
    frows = []
    for k in sorted(fam):
        d = fam[k]
        n = d["VALID"] + d["REVIEW"] + d["INVALID"]
        frows.append([k, n, d["VALID"], d["REVIEW"], d["INVALID"],
                      "%.1f" % (100.0 * d["VALID"] / n), "%.1f" % (100.0 * d["INVALID"] / n)])
    tv = sum(x[2] for x in frows)
    tr = sum(x[3] for x in frows)
    ti = sum(x[4] for x in frows)
    tn = tv + tr + ti
    frows.append(["ALL", tn, tv, tr, ti, "%.1f" % (100.0 * tv / tn), "%.1f" % (100.0 * ti / tn)])
    write("set1_family_status_matrix.csv",
          ["prompt_family", "n", "valid", "review", "invalid", "valid_pct", "invalid_pct"], frows)
    return rows


# ---------------------------------------------------------------- Set 2
def over_counts(pre, subject):
    """(beyond threshold, beyond ceiling) from a summary file.

    Two summary schemas exist: the five later phases carry
    events_beyond_threshold / events_beyond_ceiling, while candidate #1's
    per-phase summary names the columns after the distance itself. The
    threshold column is read off attack_range_cm so the two agree.
    """
    rows = [x for x in read_gp("%s_summary.csv" % pre) if x["subject"] == subject]
    thr = sum(int(x["events_beyond_300cm"]) for x in rows) if "events_beyond_300cm" in rows[0] \
        else sum(int(x["events_beyond_threshold"]) for x in rows)
    ceil = sum(int(x["events_beyond_350cm"]) for x in rows) if "events_beyond_350cm" in rows[0] \
        else sum(int(x["events_beyond_ceiling"]) for x in rows)
    return thr, ceil


def summary_rate(pre, subject):
    vals = [fnum(x.get("mean_sample_rate_hz"), None)
            for x in read_gp("%s_summary.csv" % pre) if x["subject"] == subject]
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def build_set2():
    metrics = {}
    phase_all = []
    for no, sid, tree, pre, thr, nodes, status, finding in CAND:
        sub = {}
        for subject in ("generated", "baseline"):
            prs = read_gp("%s_phase_metrics_%s.csv" % (pre, subject))
            for r in prs:
                row = {"candidate_no": no, "sample_id": sid}
                for k in r:
                    row[k] = r[k]
                phase_all.append(row)
            ev = sum(int(r["damage_events"]) for r in prs)
            dmg = sum(fnum(r["damage_total"], 0.0) for r in prs)
            fds = []
            for r in prs:
                if int(r["damage_events"]) > 0:
                    v = fnum(r["first_damage_s"])
                    if v is not None and v > 0:
                        fds.append(v)
            gmax = []
            gmin = []
            for r in prs:
                if int(r["damage_events"]) > 0:
                    a = fnum(r["max_geo_at_damage_cm"], -1.0)
                    b = fnum(r["min_geo_at_damage_cm"], -1.0)
                    if a is not None and a > 0:
                        gmax.append(a)
                    if b is not None and b > 0:
                        gmin.append(b)
            rates = [fnum(x["sample_rate_hz"], 0.0) for x in prs]
            sub[subject] = {
                "events": ev, "damage": dmg,
                "rate": summary_rate(pre, subject) or (sum(rates) / len(rates)),
                "fd_min": min(fds) if fds else None,
                "fd_mean": (sum(fds) / len(fds)) if fds else None,
                "fd_max": max(fds) if fds else None,
                "gmax": max(gmax) if gmax else None,
                "gmin": min(gmin) if gmin else None,
                "over_t": over_counts(pre, subject)[0],
                "over_c": over_counts(pre, subject)[1],
            }
        metrics[no] = sub

    rows = []
    tot_gen = 0.0
    tot_base = 0.0
    for no, sid, tree, pre, thr, nodes, status, finding in CAND:
        g = metrics[no]["generated"]
        b = metrics[no]["baseline"]
        tot_gen += g["damage"]
        tot_base += b["damage"]
        note = COMPLIANCE_NOTE
        if no == 1:
            note = COMPLIANCE_NOTE + ("; BASELINE_COMPARISON.md 12.2 published pass/pass, which "
                                      "contradicts its own 11 events beyond the 350 cm ceiling")
        rows.append([
            no, sid, tree, status, finding, thr, nodes, 3, 4, pre,
            g["events"], f1(g["damage"]), g["over_t"], g["over_c"],
            f1(g["gmax"]), f1(g["gmin"]),
            f2(g["fd_min"], 3), f2(g["fd_mean"], 3), f2(g["fd_max"], 3), f2(g["rate"]),
            b["events"], f1(b["damage"]), b["over_t"], b["over_c"],
            f1(b["gmax"]), f1(b["gmin"]),
            f2(b["fd_min"], 3), f2(b["fd_mean"], 3), f2(b["fd_max"], 3), f2(b["rate"]),
            ("%.1f" % (100.0 * g["damage"] / b["damage"])) if b["damage"] else "n/a",
            "pass" if g["over_c"] == 0 else "fail",
            "pass" if b["over_c"] == 0 else "fail",
            COMPLIANCE_RULE, note,
            "results/gameplay/%s_summary.csv" % pre,
        ])
    rows.append(["", "TOTAL", "", "", "", "", "", 18, 24, "",
                 sum(metrics[c[0]]["generated"]["events"] for c in CAND),
                 f1(tot_gen), "", "", "", "", "", "", "", "",
                 sum(metrics[c[0]]["baseline"]["events"] for c in CAND),
                 f1(tot_base), "", "", "", "", "", "", "", "",
                 "%.1f" % (100.0 * tot_gen / tot_base), "", "", "", "",
                 "derived from the six summary files"])

    write("set2_candidate_gameplay.csv",
          ["candidate_no", "sample_id", "tree_asset", "status", "finding", "attack_range_cm",
           "nodes", "trials", "phases", "source_prefix",
           "gen_events", "gen_damage", "gen_over_threshold", "gen_over_ceiling",
           "gen_max_geo_cm", "gen_min_geo_cm",
           "gen_first_damage_min_s", "gen_first_damage_mean_s", "gen_first_damage_max_s",
           "gen_rate_hz",
           "base_events", "base_damage", "base_over_threshold", "base_over_ceiling",
           "base_max_geo_cm", "base_min_geo_cm",
           "base_first_damage_min_s", "base_first_damage_mean_s", "base_first_damage_max_s",
           "base_rate_hz",
           "gen_damage_pct_of_baseline", "gen_range_compliance", "base_range_compliance",
           "range_compliance_rule", "range_compliance_note", "source_file"], rows)

    pcols = ["candidate_no", "sample_id", "run_id", "subject", "tree", "trial", "phase",
             "requested_cm", "duration_s", "samples", "sample_rate_hz", "damage_events",
             "damage_total", "health_at_phase_start", "max_geo_at_damage_cm",
             "min_geo_at_damage_cm", "max_bb_at_damage_cm", "first_damage_s",
             "subject_moved_cm", "subject_start_y", "subject_end_y"]
    phase_all.sort(key=lambda r: (int(r["candidate_no"]), r["subject"],
                                  int(r["trial"]), r["phase"]))
    write("set2_phase_metrics_all.csv", pcols, [[r.get(c, "") for c in pcols] for r in phase_all])
    return metrics


# ---------------------------------------------------------------- reliability
def build_reliability(metrics):
    rows = []
    for no, sid, tree, pre, thr, nodes, status, finding in CAND:
        run_id = [x for x in read_gp("%s_summary.csv" % pre)][0]["run_id"]
        for subject in ("generated", "baseline"):
            m = metrics[no][subject]
            fast = m["rate"] >= 10.0
            note = ""
            if no == 1:
                note = "per-phase summary schema; no reaction_correctness column in the source file"
            if no == 4:
                note = "PIE ran unthrottled for this phase only"
            rows.append([
                no, run_id, subject, f2(m["rate"]), f2(1.0 / m["rate"], 3),
                f2(1.0 / m["rate"], 3), m["events"], f1(m["damage"]),
                "yes" if abs(m["damage"] - m["events"] * 5.0) < 1e-6 else "no",
                "yes",
                ("no - only phase measured at ~59 Hz; not comparable with the five ~2.9 Hz phases"
                 if fast else "yes - within the five phases measured at ~2.9 Hz"),
                ("event counts, damage totals, sub-0.1 s within-session latency" if fast
                 else "event counts, damage totals, within-session latency"),
                note,
            ])
    write("metric_reliability.csv",
          ["candidate_no", "run_id", "subject", "mean_sample_rate_hz", "mean_interval_s",
           "first_damage_resolution_s", "damage_events", "damage_total",
           "damage_total_equals_events_x_5", "within_session_latency_valid",
           "cross_candidate_latency_comparable", "metrics_usable", "note"], rows)


# ---------------------------------------------------------------- Phase 7H
# role / direction / note are curated; every number is read back from the run's
# own phase file when one exists.
DIAG = [
    ("G1GUARD", "BT_Test_Decorator_Guard250",
     "control: dev-only decorator guard (d < 250)", "none",
     "leaf entered 12x in 8 s at 200 cm and 0x at 600 cm; no attack node, so no damage is expected"),
    ("G1DIAG", "BT_Test_Decorator_Guard250",
     "control: runtime state diagnostic", "none",
     "BrainComponent.is_running() = 1 in 41/41 samples while get_move_status() stayed Idle"),
    ("G1P03R1", "BT_Behavior_P03_G02_R1",
     "rebuild of candidate #5 (diagnostic instrument, not a candidate)", "toward the player",
     "14 nodes, 0 property differences from BT_Behavior_P03_G02"),
    ("G1P03ORIG", "BT_Behavior_P03_G02",
     "candidate #5 as built (preserved research artefact)", "away from the player",
     "identical authored graph, yet never fires; this is the as-built record, not a re-run"),
    ("G1P03R1B", "BT_Behavior_P03_G02_R1",
     "rebuild repeated (A/B/A run order)", "toward the player",
     "reproduces G1P03R1, so run order cannot explain the divergence"),
]


def build_diag():
    rows = []
    for run, tree, role, direction, note in DIAG:
        path = os.path.join(GAMEPLAY, run + "_phases.csv")
        if os.path.isfile(path):
            prs = read(path)
            disp = " / ".join(f1(fnum(r["enemy_moved_cm"], 0.0)) for r in prs)
            dmg = " / ".join(whole(r["damage_total"]) for r in prs)
            fired = " / ".join(str(r["weapon_fired"]) for r in prs)
            rate = f2(sum(fnum(r["sample_rate_hz"], 0.0) for r in prs) / len(prs))
        else:
            disp, dmg, fired, rate = "n/a / n/a / n/a / n/a", "n/a", "n/a", "n/a"
        rows.append([run, tree, role, disp, direction, dmg, fired, rate, note])
    write("phase7h_rebuild_diagnostics.csv",
          ["run_id", "tree_asset", "role", "displacement_cm", "displacement_direction",
           "damage_by_phase", "weapon_fired_by_phase", "mean_sample_rate_hz", "note"], rows)


# ---------------------------------------------------------------- curated
AR = [
 ("1", "P01-G01", "move_to_target", "yes", "reached", "BTTask_EnemyMoveToTarget SUCCESS 9, FAILURE 0; 0 failures in 3 trials", "none"),
 ("1", "P01-G01", "move_away_from_target", "no", "not_in_tree", "tree has no retreat node; retreat_distance_cm is a dead parameter", "none"),
 ("1", "P01-G01", "attack", "yes", "reached", "36 damage events; 0 out-of-range refusals recovered from Saved/Logs (gap G2)", "none"),
 ("1", "P01-G01", "wait", "yes", "unobservable", "BTTask_Wait prints nothing; position in the tree is not measurement", "none"),
 ("2", "P02-G01", "move_to_target", "yes", "reached", "BTTask_EnemyMoveToTarget SUCCESS 6, FAILURE 0", "none"),
 ("2", "P02-G01", "move_away_from_target", "yes", "reached", "retreat SUCCESS 1 at 1718.2 cm then FAILURE (already beyond retreat range); sawtooth re-arms", "none"),
 ("2", "P02-G01", "attack", "yes", "unreachable", "BTTask_EnemyAttack 0 lines, 0 damage in 3 trials; n5's own arrival band returns the pawn inside the d>800 it must satisfy", "generated_logic"),
 ("2", "P02-G01", "wait", "yes", "satisfies_selector", "not directly observable; a sequence ending in an unguarded Wait closes the selector before the attack sequence on every pass", "generated_logic"),
 ("3", "P04-G01", "move_to_target", "yes", "reached", "BTTask_EnemyMoveToTarget SUCCESS 6, FAILURE 1 (1 arrived too far)", "none"),
 ("3", "P04-G01", "move_away_from_target", "yes", "entered_never_succeeds", "retreat FAILURE 24 (23 retreat too short, 1 no target), SUCCESS 0; retreat_distance_cm 2000 exceeds the 1976 cm navmesh extent", "generated_logic+environment_navigation"),
 ("3", "P04-G01", "attack", "yes", "reached", "35 damage events, 0 refusals; but only through the two bands that are satisfiable", "none"),
 ("3", "P04-G01", "wait", "yes", "unobservable", "BTTask_Wait prints nothing", "none"),
 ("6", "P07-G01", "move_to_target", "no", "not_in_tree", "tree has no approach node", "none"),
 ("6", "P07-G01", "move_away_from_target", "yes", "never_executes", "retreat FAILURE 1 (no target), SUCCESS 0; FlowAbortMode=Self ends the branch 250 cm before its own success test", "generated_logic"),
 ("6", "P07-G01", "attack", "yes", "entered_always_refused", "BTTask_EnemyAttack 106 entries, 106 out-of-range refusals, 0 damage; d>=900 gate against AttackRange 900 is a zero-width window", "generated_logic"),
 ("6", "P07-G01", "wait", "yes", "unobservable", "BTTask_Wait prints nothing", "none"),
 ("5", "P03-G02", "move_to_target", "yes", "reached", "BTTask_EnemyMoveToTarget SUCCESS 21, FAILURE 1", "none"),
 ("5", "P03-G02", "move_away_from_target", "yes", "reached", "retreat SUCCESS 11, FAILURE 22 (16 retreat too short, 5 already beyond range, 1 no target)", "none"),
 ("5", "P03-G02", "attack", "yes", "entered_always_refused", "BTTask_EnemyAttack 1 entry, 1 refusal at ~1500 cm, 0 damage; the graph-identical rebuild BT_Behavior_P03_G02_R1 attacks 15-25 per phase, so the as-built outcome is an asset-level discrepancy, not the authored tree", "compiled_asset_discrepancy"),
 ("5", "P03-G02", "wait", "yes", "unobservable", "BTTask_Wait prints nothing; phase 7F inferred two unguarded Waits were satisfying the selector, which G1 withdraws", "none"),
 ("4", "P01-G02", "move_to_target", "yes", "reached", "BTTask_EnemyMoveToTarget SUCCESS 9, FAILURE 0", "none"),
 ("4", "P01-G02", "move_away_from_target", "no", "not_in_tree", "tree has no retreat node; retreat_distance_cm 600 is a dead parameter", "none"),
 ("4", "P01-G02", "attack", "yes", "reached", "55 damage events; 10 out-of-range refusals at ~950 cm proved the in-task gate is load-bearing", "none"),
 ("4", "P01-G02", "wait", "yes", "unobservable", "BTTask_Wait prints nothing; 0.1 s duration not measurable", "none"),
]

FA = [
 ["F01", "Set 2", "1 / P01-G01", "No behavioural failure observed",
  "36 damage events / 180.0 damage; 0 events beyond 300 cm; 9 move SUCCESS, 0 FAILURE; 0 attack refusals recovered from Saved/Logs/Cosmic_Animossity.log (gap G2, 01:02:40-01:03:54)",
  "none", "none", "no", "yes", "closed"],
 ["F02", "Set 2", "2 / P02-G01", "attack branch never executes",
  "BTTask_EnemyAttack 0 lines and 0 damage in 3 trials while the retreat/approach sawtooth ran 6 approach successes and 1 retreat success",
  "generated_logic", "engine_task_behaviour (AcceptanceRadius = attack_range_cm - 150 chosen by the implementation returns the pawn inside the d>800 window)", "yes", "yes", "closed"],
 ["F03", "Set 2", "2 / P02-G01", "retreat/approach sawtooth every pass",
  "retreat SUCCESS at 1718.2 cm, then FAILURE (already beyond retreat range), fall-through to approach, re-arm inside 1200 cm",
  "generated_logic", "none", "yes", "yes", "closed (predicted in Phase 5C, measured in 7C)"],
 ["F04", "Set 2", "3 / P04-G01", "close distance band unreachable",
  "retreat FAILURE 24 (23 retreat too short, 1 no target), SUCCESS 0; generated retreat_distance_cm 2000 exceeds the arena navmesh extent (~1976 cm), so n2 can never succeed and n3/n4 are dead",
  "generated_logic", "environment_navigation", "yes", "yes", "closed"],
 ["F05", "Set 2", "3 / P04-G01", "one approach failure (arrived too far)",
  "BTTask_EnemyMoveToTarget FAILURE 1, of which 1 arrived too far",
  "engine_task_behaviour", "none", "no", "partial", "open (arrival band vs stop overshoot)"],
 ["F06", "Set 2", "6 / P07-G01", "attack window is zero-width",
  "BTTask_EnemyAttack 106 entries, 106 out-of-range refusals, 0 damage; the authored d>=900 decorator against an AttackRange of 900 admits only d == 900.0",
  "generated_logic", "none", "yes", "yes", "closed"],
 ["F07", "Set 2", "6 / P07-G01", "retreat branch never reaches its own success test",
  "retreat SUCCESS 0, FAILURE 1 (no target); FlowAbortMode=Self ends the sequence 250 cm before the 150 cm success band is satisfied",
  "generated_logic", "engine_task_behaviour", "yes", "partial", "open (trial-level abort timing unmeasured)"],
 ["F08", "Set 2", "5 / P03-G02", "as-built asset deals zero damage",
  "0 damage events in 3 comparison trials; asset retreats 834-835 cm at far range; the node-for-node rebuild BT_Behavior_P03_G02_R1 attacks 15/20/20/20 and 20/25/25/20 in the same session. Established: the two assets behave differently while their authored graphs are identical, so the difference lies outside what the graph read-back covers",
  "compiled_asset_discrepancy", "generated_logic (withdrawn as the explanation)", "no", "no", "open (asset-level divergence established; which compiled field carries it is unresolved)"],
 ["F09", "Set 2", "5 / P03-G02", "L5 risk was never exercised",
  "n8 entered once and refused once at ~1500 cm; no shot was ever attempted inside 1000 cm, so 'would the ungated attack fire out of range' has no measurement",
  "instrumentation", "none", "n/a", "no", "open (unmeasurable with current observables)"],
 ["F10", "Set 2", "5 / P03-G02", "leaf decorators appeared inert (Phase 7F claim, now withdrawn)",
  "superseded by Phase 7H: the guard control entered its leaf 12x in 8 s at 200 cm and 0x at 600 cm, and candidate #6's preserved data moved 0.0 cm in both 1500 cm phases under a d<900 decorator",
  "instrumentation", "compiled_asset_discrepancy", "no", "yes", "withdrawn - decorator enforcement is not the defect"],
 ["F11", "Set 2", "4 / P01-G02", "10 attack entries refused out of band (~950 cm)",
  "BTTask_EnemyAttack 10 lines, 10 out-of-range refusals; decorator and in-task gate both read DistanceToTarget against 250 cm",
  "engine_task_behaviour", "none", "no", "yes", "closed (gate is load-bearing, not a defect)"],
 ["F12", "Set 2", "4 / P01-G02", "one damage event recorded 0.1 cm outside the band",
  "1 event at 250.1 cm; projectiles = 1 preceded it by 35 ms and the pawn had not moved",
  "instrumentation", "none", "no", "yes", "closed (cross-phase carry-over, excluded from both columns)"],
 ["F13", "Set 2", "4 / P01-G02", "trial 3 far_1500_again overshoot",
  "1512.3 cm travelled, 546.0 cm end separation; the pawn ran past a stationary target and never returned inside the band before the phase ended",
  "unattributed", "environment_navigation", "no", "no", "open (1 phase of 12)"],
 ["F14", "All Set 2", "all subjects", "phase-start DistanceToTarget is stale",
  "DistanceToTarget is a 0.1 s staircase written by AIController_ResearchEnemy; the first frame of a phase can read 0.0 or the previous phase's distance, and a decorator can admit one entry on that key (measured once: already beyond retreat range d=1500.02)",
  "engine_task_behaviour", "instrumentation", "no", "yes", "closed as a mechanism, unresolved as a per-phase effect"],
 ["F15", "All Set 2", "six baselines", "blameless baseline scores 'fail' on the compliance rule",
  "over-threshold events at the matching thresholds: 12, 8, 0, 4, 3, 16; the threshold is each candidate's authored attack_range_cm and the baseline has no authored range",
  "metric_definition", "none", "no", "yes", "closed (documented artefact, not baseline drift)"],
 ["F16", "Instrumentation", "all six candidates", "sample rate differs by a factor of 20 across phases",
  "2.89-2.93 Hz for candidates 1, 2, 3, 6, 5 versus 59.48 / 58.65 Hz for candidate 4; first-damage resolution is +/-0.34 s versus +/-0.017 s",
  "instrumentation", "none", "no", "yes", "closed (counts and totals exact at both rates; cross-rate latency comparison invalid)"],
 ["F17", "Reporting", "1 / P01-G01", "published baseline minimum at damage is an upper bound",
  "RESEARCH_PROGRESS.md 12.2 gives '<= 82.1 cm'; the per-phase minimum recomputed here is 68.8 cm (trial 3, far_1500)",
  "instrumentation", "none", "no", "yes", "corrected in this analysis"],
 ["F18", "Reporting", "1 / P01-G01", "published candidate-1 compliance verdict pair was inconsistent",
  "RESEARCH_PROGRESS.md 12.2 gives 'pass / pass' while also recording 11 baseline events beyond the 350 cm ceiling; the uniform rule (0 events beyond ceiling) yields gen pass / base fail",
  "metric_definition", "none", "no", "yes", "corrected in this analysis"],
 ["F19", "Scope", "14 INVALID outputs", "14 INVALID trees were never built or measured",
  "10 rows carry S1 (single-child composite) and 6 carry S5 (retreat_distance_cm <= attack_range_cm); none was translated, so no gameplay claim about them exists",
  "scope_limitation", "none", "n/a", "n/a", "open by design"],
 ["F20", "Scope", "12 REVIEW outputs", "12 of the 14 REVIEW outputs were never built",
  "11 x L5 and 1 x L3 remain unbuilt; P03-G02 (L5) and P01-G02 (L3) were measured",
  "scope_limitation", "none", "n/a", "n/a", "open by design"],
]


def build_curated():
    write("action_reachability.csv",
          ["candidate_no", "sample_id", "action", "present_in_tree", "reachability", "evidence",
           "attribution"], AR)
    write("failure_attribution.csv",
          ["id", "evaluation_set", "subject", "observation", "evidence", "primary_attribution",
           "contributing_attribution", "generated_logic_failure", "mechanism_resolved", "status"], FA)


def main():
    build_set1()
    metrics = build_set2()
    build_reliability(metrics)
    build_diag()
    build_curated()

    gen = [metrics[c[0]]["generated"]["damage"] for c in CAND]
    base = [metrics[c[0]]["baseline"]["damage"] for c in CAND]
    zero = [c[0] for c in CAND if metrics[c[0]]["generated"]["damage"] == 0.0]
    print("")
    print("cross-check, generated damage by candidate: %s" % gen)
    print("cross-check, baseline  damage by candidate: %s" % base)
    print("cross-check, totals generated=%.1f baseline=%.1f (%.1f %%)"
          % (sum(gen), sum(base), 100.0 * sum(gen) / sum(base)))
    print("cross-check, zero-damage candidates: %s (%d of 6)" % (zero, len(zero)))


if __name__ == "__main__":
    main()
